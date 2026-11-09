from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.prepare_software_exploration_s2 import read_json, sha256, write_json


EXPERIMENT = Path("evaluation/software-exploration/experiments")
TOOL_BUNDLE = Path(
    "C:/Users/28320/.codex/plugins/cache/openai-bundled/computer-use/26.1023.50603"
)


def prepare(root: Path, tool_bundle: Path = TOOL_BUNDLE) -> dict[str, Any]:
    previous = root / EXPERIMENT / "round-01"
    target = root / EXPERIMENT / "round-02"
    artifact_root = root / "artifacts/software-exploration/round-02"
    if (target / "freeze.json").exists() or artifact_root.exists():
        raise FileExistsError("round-02 已生成；拒绝覆盖冻结包或运行证据")

    frozen = read_json(previous / "freeze.json")
    for item in frozen["files"]:
        source = root / item["path"]
        if source.stat().st_size != item["size_bytes"] or sha256(source) != item["sha256"]:
            raise ValueError(f"上一轮冻结文件漂移：{item['path']}")

    docs = [
        tool_bundle / "skills/computer-use/SKILL.md",
        tool_bundle / "docs/guidance.md",
        tool_bundle / "docs/api.md",
        tool_bundle / "docs/confirmations.md",
    ]
    tool_texts = [path.read_text(encoding="utf-8") for path in docs]
    schema_path = root / "schemas/software-exploration-report.schema.json"
    schema_text = schema_path.read_text(encoding="utf-8")
    prompt = (target / "test-agent-prompt.md").read_text(encoding="utf-8")
    (target / "protocol-addendum.md").read_text(encoding="utf-8")

    target.mkdir(parents=True, exist_ok=True)
    (target / "inputs").mkdir()
    (target / "dispatch").mkdir()
    for name in ("s2-a-verified-requirements.json", "s2-b-s1-baseline.json"):
        shutil.copy2(previous / "inputs" / name, target / "inputs" / name)
    shutil.copy2(previous / "protocol.md", target / "protocol-base.md")
    shutil.copy2(previous / "isolation.md", target / "isolation.md")
    shutil.copy2(schema_path, target / "report.schema.json")
    (target / "tool-guide.md").write_text(
        "\n\n".join(tool_texts), encoding="utf-8", newline="\n"
    )

    dispatches = []
    for run_id, name, role in (
        ("s2-a", "s2-a-verified-requirements.json", "verified-upstream"),
        ("s2-b", "s2-b-s1-baseline.json", "s1-actual-output"),
    ):
        packet = target / "dispatch" / f"{run_id}.md"
        packet.write_text(
            f"本次 run_id={run_id}；input_role={role}。\n\n" + prompt
            + "\n\n## 完整报告 Schema\n\n" + schema_text
            + "\n\n## 允许工具文档\n\n" + "\n\n".join(tool_texts)
            + "\n\n## 需求输入\n\n"
            + (target / "inputs" / name).read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n",
        )
        dispatches.append(packet)

    environment = {
        "schema_version": "software-exploration-environment/v1",
        "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "role": "calibration",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "working_tree_changes": subprocess.check_output(
            ["git", "status", "--porcelain=v1"], cwd=root, text=True, encoding="utf-8"
        ).splitlines(),
        "computer_use_bundle": tool_bundle.name,
        "previous_computer_use_bundle": "26.1021.31345",
        "uia_entry": "mcp__node_repl__js + @oai/sky",
        "runtime_version_verified": False,
        "comparability": "文档包版本不同；需恢复后以独立健康检查核实实质行为，不合并成绩。",
        "tool_documents": [
            {"path": str(path), "sha256": sha256(path)} for path in docs
        ],
    }
    write_json(target / "environment.json", environment)

    exe = root / "artifacts/miniorder/blackbox-run/MiniOrder.exe"
    seed = root / "samples/MiniOrder/evaluation/seed/orders.json"
    runtime_files = []
    for run_id in ("health-check", "s2-a", "s2-b"):
        for source, destination in (
            (exe, artifact_root / run_id / "sut/MiniOrder.exe"),
            (seed, artifact_root / run_id / "data/orders.json"),
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            runtime_files.append(destination)

    old_reports = []
    for run_id in ("s2-a", "s2-b"):
        for name in ("raw-report.json", "report-lock.json"):
            old_reports.append(root / "artifacts/software-exploration/round-01" / run_id / name)
    tracked = [root / item["path"] for item in frozen["files"]]
    tracked += list(target.glob("*.md")) + list(target.glob("*.json"))
    tracked += list((target / "inputs").glob("*.json")) + dispatches
    tracked += runtime_files + old_reports
    tracked += [Path(__file__).resolve(), root / "scripts/evaluate_software_exploration_s2.py"]
    paths = sorted(set(tracked))
    manifest = {
        "schema_version": "software-exploration-freeze/v1",
        "role": "calibration",
        "frozen": True,
        "budget": frozen["budget"],
        "thresholds": frozen["thresholds"],
        "files": [
            {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size,
             "sha256": sha256(path)} for path in paths
        ],
    }
    write_json(target / "freeze.json", manifest)
    write_json(target / "freeze-lock.json", {
        "algorithm": "sha256 of exact freeze.json bytes",
        "sha256": sha256(target / "freeze.json"),
    })
    return {"freeze_sha256": sha256(target / "freeze.json"), "files": len(paths),
            "dispatch_sha256": {path.name: sha256(path) for path in dispatches}}


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 S2 round-02 校准材料，拒绝覆盖既有运行")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(prepare(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
