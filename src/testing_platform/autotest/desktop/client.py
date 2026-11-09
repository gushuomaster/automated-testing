"""Client for the desktop execution service: subprocess + per-call timeout + auto restart."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


class ToolTimeout(Exception):
    """The service did not answer in time; it was killed and restarted."""


class ServiceError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


class DesktopClient:
    def __init__(self, out_dir: str | Path, command: list[str] | None = None, default_timeout: float = 30.0):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.command = command or [sys.executable, "-m", "testing_platform.autotest.desktop.service",
                                   "--out", str(self.out_dir)]
        self.default_timeout = default_timeout
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()
        self.next_id = 0
        self.target: list[int] | None = None
        self.restarts = 0
        self._stderr = None

    # ---- lifecycle ----------------------------------------------------------------------
    def start(self) -> None:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        self._stderr = open(self.out_dir / "service.stderr.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._stderr, env=env, text=True, encoding="utf-8",
                                     bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc, self.lines), daemon=True).start()

    @staticmethod
    def _reader(proc: subprocess.Popen, lines: queue.Queue) -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.proc = None
        if self._stderr:
            self._stderr.close()
            self._stderr = None

    def restart(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
        if self._stderr:
            self._stderr.close()
        self.restarts += 1
        self.start()
        if self.target is not None:
            self.call("set_target", pids=self.target)

    def __enter__(self) -> "DesktopClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- rpc ----------------------------------------------------------------------------
    def call(self, op: str, timeout: float | None = None, **args):
        if self.proc is None or self.proc.poll() is not None:
            self.restart() if self.proc is not None else self.start()
        self.next_id += 1
        req_id = self.next_id
        self.proc.stdin.write(json.dumps({"id": req_id, "op": op, "args": args}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        limit = timeout or self.default_timeout
        while True:
            try:
                line = self.lines.get(timeout=limit)
            except queue.Empty:
                self.restart()
                raise ToolTimeout(f"{op} did not finish within {limit:.0f}s; service restarted") from None
            if line is None:
                self.restart()
                raise ServiceError("ServiceDied", f"service exited during {op}; restarted")
            resp = json.loads(line)
            if resp.get("id") != req_id:
                continue  # stale answer from a call that already timed out
            if resp["ok"]:
                if op == "set_target":
                    self.target = list(args["pids"])
                return resp["result"]
            raise ServiceError(resp.get("kind", "Error"), resp.get("error", ""))
