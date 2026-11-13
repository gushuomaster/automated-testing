"""Host-side client for remote_server.py: same call() interface as DesktopClient, over TCP.

Screenshots are fetched from the guest after every observe and the returned paths point at the local
copies, so the agent does not know the desktop is remote. The token is never logged or put in errors.
"""

from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

from .client import ServiceError, ToolTimeout


class RemoteDesktopClient:
    def __init__(self, host: str, port: int, token: str, out_dir: str | Path,
                 default_timeout: float = 30.0, connect_timeout: float = 10.0):
        self.host, self.port, self.token = host, port, token
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.default_timeout = default_timeout
        self.connect_timeout = connect_timeout
        self.sock: socket.socket | None = None
        self.rd = None
        self.wr = None
        self.next_id = 0
        self.target: list[int] | None = None
        self.restarts = 0

    # ---- lifecycle ----------------------------------------------------------------------
    def start(self) -> None:
        self._connect()

    def close(self) -> None:
        self._drop()

    def restart(self) -> None:
        self.restarts += 1
        self._connect()

    def __enter__(self) -> "RemoteDesktopClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _drop(self) -> None:
        for res in (self.rd, self.wr, self.sock):
            try:
                if res is not None:
                    res.close()
            except OSError:
                pass
        self.sock = self.rd = self.wr = None

    def _connect(self) -> None:
        self._drop()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
            self.sock = sock
            self.rd = sock.makefile("r", encoding="utf-8", newline="\n")
            self.wr = sock.makefile("w", encoding="utf-8", newline="\n")
            self.wr.write(json.dumps({"auth": self.token}) + "\n")
            self.wr.flush()
            reply = self.rd.readline()
            ok = bool(reply) and bool(json.loads(reply).get("ok"))
        except (OSError, ValueError) as exc:
            self._drop()
            raise ServiceError("ConnectionFailed", f"cannot reach remote service {self.host}:{self.port} "
                                                  f"({type(exc).__name__})") from None
        if not ok:
            self._drop()
            raise ServiceError("AuthFailed", "remote service rejected the token")

    # ---- rpc ----------------------------------------------------------------------------
    def _rpc(self, op: str, timeout: float | None, **args):
        if self.sock is None:
            self._connect()
        self.next_id += 1
        req_id = self.next_id
        limit = timeout or self.default_timeout
        self.sock.settimeout(limit + 15)  # the server enforces `limit`; this only guards a dead link
        try:
            self.wr.write(json.dumps({"id": req_id, "op": op, "args": args, "timeout": limit},
                                     ensure_ascii=False) + "\n")
            self.wr.flush()
            while True:
                line = self.rd.readline()
                if not line:
                    raise ConnectionError("connection closed")
                resp = json.loads(line)
                if resp.get("id") == req_id:  # skip a stale answer from an earlier call
                    break
        except (OSError, ValueError) as exc:
            self._drop()
            self.restarts += 1
            raise ToolTimeout(f"{op}: no answer from the remote service ({type(exc).__name__}); "
                              f"will reconnect") from None
        if resp["ok"]:
            return resp["result"]
        if resp.get("kind") == "ToolTimeout":
            raise ToolTimeout(resp.get("error", ""))
        raise ServiceError(resp.get("kind", "Error"), resp.get("error", ""))

    def call(self, op: str, timeout: float | None = None, **args):
        result = self._rpc(op, timeout, **args)
        if op == "set_target":
            self.target = list(args["pids"])
        if op == "observe":
            result = self._localize(result)
        return result

    def _localize(self, obs: dict) -> dict:
        """Fetch the guest's screenshots and point the observation at the local copies."""
        local: dict[str, str] = {}
        for key in ("screenshot", "annotated"):
            remote = obs[key]
            if remote not in local:
                got = self._rpc("fetch_file", None, path=remote)
                dest = self.out_dir / got["name"]
                dest.write_bytes(base64.b64decode(got["data"]))
                local[remote] = str(dest)
            obs[key] = local[remote]
        return obs
