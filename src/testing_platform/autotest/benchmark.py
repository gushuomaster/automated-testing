"""Run the KeePassXC M0 benchmark: reset -> launch -> agent -> close (discard unsaved) -> verify.

    python -m testing_platform.autotest.benchmark --tasks T01,T02 [--model claude-opus-5-5] [--effort medium]

Requires ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN (or ANTHROPIC_API_KEY) in the environment.
Nobody should use the mouse/keyboard while it runs (shared desktop until M1 moves it into a VM).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .agent import Agent, Budget, RunResult
from .apps.keepassxc import KeePassXCEnv, parse_export
from .checks import evaluate
from .desktop.client import DesktopClient
from .model import ClaudeModel, Usage

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SUITE = REPO / "benchmarks" / "keepassxc-m0"
DEFAULT_APP = REPO / "artifacts" / "feasibility-01" / "downloads" / "kpxc-2.7.6" / "app" / "KeePassXC-2.7.6-Win64"
SELF_REPORTED = ("completed", "failed", "blocked")


def run_task(task: dict, suite: dict, suite_dir: Path, app_dir: Path, out_dir: Path,
             model: ClaudeModel, budget_args: dict) -> dict:
    task_dir = out_dir / task["id"]
    env = KeePassXCEnv(app_dir=app_dir, seed_db=suite_dir / suite["seed"], password=suite["password"],
                       run_dir=task_dir / "data")
    env.reset()
    seed = parse_export(env.export_xml())
    pid = env.launch()
    model.usage = Usage()
    result: RunResult
    with DesktopClient(task_dir / "shots") as desktop:
        desktop.call("set_target", pids=[pid])
        agent = Agent(model, desktop, task_dir, budget=Budget(**budget_args))
        try:
            result = agent.run(task["prompt"])
        except Exception as exc:  # harness bug: record and keep going
            traceback.print_exc()
            result = agent._result("error", error=f"{type(exc).__name__}: {exc}")
    stop_log = env.stop()

    snap, snap_error = None, ""
    try:
        snap = env.snapshot()
    except Exception as exc:
        snap_error = str(exc)
    verdict = evaluate(task, snap, seed, env.read_config(), result.answer)
    claimed = result.outcome == "completed"
    record = {
        "id": task["id"],
        "kind": task["kind"],
        "passed": verdict["passed"],
        "claimed_success": claimed,
        "false_success": claimed and not verdict["passed"],
        "outcome": result.outcome,
        "answer": result.answer,
        "summary": result.summary,
        "verdict": verdict,
        "snapshot_error": snap_error,
        "run": result.to_dict(),
        "stop": stop_log,
    }
    (task_dir / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def summarize(records: list[dict], model: str, effort: str | None) -> dict:
    n = len(records)
    total = Usage()
    for r in records:
        for k, v in r["run"]["usage"].items():
            if hasattr(total, k) and k != "calls":
                setattr(total, k, getattr(total, k) + v)
        total.calls += r["run"]["usage"].get("calls", 0)
    return {
        "model": model,
        "effort": effort,
        "tasks": n,
        "passed": sum(r["passed"] for r in records),
        "pass_rate": round(sum(r["passed"] for r in records) / n, 3) if n else None,
        "claimed_success": sum(r["claimed_success"] for r in records),
        "false_success": sum(r["false_success"] for r in records),
        "honest_failure": sum((not r["passed"]) and not r["claimed_success"] for r in records),
        "actions_total": sum(r["run"]["actions"] for r in records),
        "seconds_total": round(sum(r["run"]["seconds"] for r in records), 1),
        "refused_total": sum(r["run"]["refused"] for r in records),
        "timeouts_total": sum(r["run"]["timeouts"] for r in records),
        "usage": total.to_dict(model),
        "per_task": [{k: r[k] for k in ("id", "passed", "outcome", "false_success")}
                     | {"actions": r["run"]["actions"], "seconds": r["run"]["seconds"],
                        "collateral": r["verdict"]["collateral"],
                        "failed_checks": [c["detail"] for c in r["verdict"]["checks"] if not c["ok"]]}
                     for r in records],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    p.add_argument("--app-dir", type=Path, default=Path(os.environ.get("KPXC_APP_DIR", DEFAULT_APP)))
    p.add_argument("--tasks", help="comma-separated task ids (default: all)")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium", help="low|medium|high|xhigh|max or 'none' to omit")
    p.add_argument("--max-actions", type=int, default=30)
    p.add_argument("--max-seconds", type=float, default=480)
    p.add_argument("--max-model-calls", type=int, default=45)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("missing ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    suite = json.loads((args.suite / "tasks.json").read_text(encoding="utf-8"))
    wanted = set(args.tasks.split(",")) if args.tasks else None
    tasks = [t for t in suite["tasks"] if wanted is None or t["id"] in wanted]
    out_dir = args.out or REPO / "artifacts" / "m0-runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    effort = None if args.effort == "none" else args.effort
    model = ClaudeModel(model=args.model, effort=effort)
    budget_args = {"max_actions": args.max_actions, "max_seconds": args.max_seconds,
                   "max_model_calls": args.max_model_calls}

    records = []
    for task in tasks:
        print(f"[{datetime.now():%H:%M:%S}] {task['id']} ...", flush=True)
        record = run_task(task, suite, args.suite, args.app_dir, out_dir, model, budget_args)
        records.append(record)
        print(f"  passed={record['passed']} outcome={record['outcome']} actions={record['run']['actions']} "
              f"seconds={record['run']['seconds']}", flush=True)
        summary = summarize(records, args.model, effort)
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summarize(records, args.model, effort), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
