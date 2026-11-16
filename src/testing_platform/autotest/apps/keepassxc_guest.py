"""Guest-side KeePassXC control for remote_server: a fixed set of ops, no arbitrary command execution.

Runs inside the VM guest's desktop session. Ops: kpxc_reset, kpxc_launch, kpxc_stop, kpxc_export, kpxc_config.
The seed database can only come from <root>/benchmarks; all other paths are fixed under <root>.

Each op runs in a short-lived child process (`python -m testing_platform.autotest.apps.keepassxc_guest`).
stop() drives UI Automation through COM/ctypes; doing that on remote_server's per-connection threads crashed
the whole server with an access violation in _ctypes (run-02-vm, 2026-11-13). In a child process COM starts
fresh every time and a crash only fails that op. State between ops (seed, password) lives in <root>/run/state.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .keepassxc import KeePassXCEnv, stop as stop_all

GUEST_ROOT = Path("C:/autotest")
OPS = ("kpxc_reset", "kpxc_launch", "kpxc_stop", "kpxc_export", "kpxc_config")
OP_TIMEOUT = 120.0
SRC_DIR = Path(__file__).resolve().parents[3]  # the directory holding the testing_platform package


class GuestKeePassXC:
    def __init__(self, root: Path = GUEST_ROOT) -> None:
        self.root = Path(root)
        self.app_dir = self.root / "KeePassXC"
        self.state_file = self.root / "run" / "state.json"
        self.env: KeePassXCEnv | None = None

    def _make_env(self, seed_path: Path, password: str) -> KeePassXCEnv:
        return KeePassXCEnv(app_dir=self.app_dir, seed_db=seed_path, password=password, run_dir=self.root / "run")

    def _need(self) -> KeePassXCEnv:
        if self.env is None and self.state_file.is_file():
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.env = self._make_env(Path(state["seed"]), state["password"])
        if self.env is None:
            raise RuntimeError("kpxc_reset must be called first")
        return self.env

    def reset(self, seed: str, password: str) -> dict:
        bench = (self.root / "benchmarks").resolve()
        seed_path = (bench / seed).resolve()
        if not seed_path.is_relative_to(bench) or not seed_path.is_file():
            raise ValueError("seed must be an existing file under benchmarks")
        self.env = self._make_env(seed_path, password)
        result = self.env.reset()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"seed": str(seed_path), "password": password}), encoding="utf-8")
        return result

    def launch(self) -> dict:
        return {"pid": self._need().launch()}

    def stop(self) -> dict:
        return {"log": stop_all()}

    def export(self) -> dict:
        return {"xml": self._need().export_xml()}

    def config(self) -> dict:
        env = self._need()
        return {"ini": env.config_file.read_text(encoding="utf-8") if env.config_file.exists() else ""}

    def run_op(self, op: str, args: dict) -> dict:
        """Run one op in this process."""
        if op == "kpxc_reset":
            return self.reset(args["seed"], args["password"])
        if op == "kpxc_launch":
            return self.launch()
        if op == "kpxc_stop":
            return self.stop()
        if op == "kpxc_export":
            return self.export()
        if op == "kpxc_config":
            return self.config()
        raise ValueError(f"unknown op {op}")

    def run_isolated(self, op: str, args: dict, timeout: float = OP_TIMEOUT) -> dict:
        """Run one op in a child process; any crash, timeout or error becomes a RuntimeError here."""
        if op not in OPS:
            raise ValueError(f"unknown op {op}")
        cmd = [sys.executable, "-m", "testing_platform.autotest.apps.keepassxc_guest", "--root", str(self.root), op]
        try:
            res = subprocess.run(cmd, input=json.dumps(args), capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=timeout, cwd=str(SRC_DIR))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{op} timed out after {timeout:.0f}s") from None
        lines = [line for line in res.stdout.splitlines() if line.strip()]
        try:
            reply = json.loads(lines[-1])
        except (IndexError, ValueError):
            tail = (res.stderr or res.stdout).strip()[-300:]
            raise RuntimeError(f"{op} child exited with code {res.returncode}: {tail}") from None
        if not reply.get("ok"):
            raise RuntimeError(f"{op} failed: {reply.get('error', '')}")
        return reply["result"]

    def handlers(self, isolated: bool = True) -> dict:
        run = self.run_isolated if isolated else self.run_op
        return {op: (lambda a, op=op: run(op, a)) for op in OPS}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="run one guest KeePassXC op; args as JSON on stdin")
    parser.add_argument("--root", type=Path, default=GUEST_ROOT)
    parser.add_argument("op", choices=OPS)
    args = parser.parse_args(argv)
    # ASCII-only JSON: the pipe uses the console code page (GBK on a Chinese guest), so non-ASCII output
    # would reach the parent garbled (seen as entry-name collisions in kpxc_export).
    try:
        op_args = json.loads(sys.stdin.read() or "{}")
        result = GuestKeePassXC(args.root).run_op(args.op, op_args)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
