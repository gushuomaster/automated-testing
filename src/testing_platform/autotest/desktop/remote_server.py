"""TCP front for the desktop service, used when the target software runs in a VM guest.

    python -m testing_platform.autotest.desktop.remote_server --out DIR --token-file FILE [--host IP] [--port 8765]

JSON lines over TCP. The client's first line must be {"auth": "<token>"}; the server answers {"ok": true}
or just closes the connection. After that each request is {"id", "op", "args", "timeout"} and goes to a
local desktop service (service.py), so a hung call is still killed and the service restarted. One extra
op, fetch_file {"path"}, returns a file under --out as base64 so screenshots can travel back to the host.
The fixed kpxc_* ops (see apps/keepassxc_guest.py) are handled in this process and not forwarded.
The token is read from a file and never logged.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import socket
import threading
import traceback
from pathlib import Path

from .client import DesktopClient, ServiceError, ToolTimeout

MAX_FILE_BYTES = 20 * 1024 * 1024
AUTH_TIMEOUT = 10.0


def fetch_file(out_dir: Path, path: str) -> dict:
    target = Path(path).resolve()
    if not target.is_relative_to(out_dir.resolve()) or not target.is_file():
        raise ServiceError("Refused", "path is outside the output directory or is not a file")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ServiceError("Refused", "file too large")
    return {"name": target.name, "data": base64.b64encode(target.read_bytes()).decode("ascii")}


def execute(client, lock: threading.Lock, out_dir: Path, line: str, extra: dict | None = None) -> dict:
    """Run one request line and return the response dict (never raises).

    `extra` maps additional op names (e.g. kpxc_*) to handlers taking the args dict.
    """
    req_id = None
    try:
        req = json.loads(line)
        req_id = req.get("id")
        op, args = req["op"], req.get("args") or {}
        if op == "fetch_file":
            result = fetch_file(out_dir, args["path"])
        elif extra and op in extra:
            with lock:
                result = extra[op](args)
        else:
            with lock:
                result = client.call(op, timeout=req.get("timeout"), **args)
        return {"id": req_id, "ok": True, "result": result}
    except ToolTimeout as exc:
        return {"id": req_id, "ok": False, "kind": "ToolTimeout", "error": str(exc)}
    except ServiceError as exc:
        return {"id": req_id, "ok": False, "kind": exc.kind, "error": exc.message}
    except Exception as exc:
        traceback.print_exc()
        return {"id": req_id, "ok": False, "kind": type(exc).__name__, "error": str(exc)}


def serve_connection(conn, client, lock: threading.Lock, out_dir: Path, token: str,
                     extra: dict | None = None) -> None:
    try:
        with conn:
            conn.settimeout(AUTH_TIMEOUT)
            rd = conn.makefile("r", encoding="utf-8", newline="\n")
            wr = conn.makefile("w", encoding="utf-8", newline="\n")
            try:
                supplied = str(json.loads(rd.readline()).get("auth", ""))
            except Exception:
                return
            if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                return
            conn.settimeout(None)
            wr.write(json.dumps({"ok": True}) + "\n")
            wr.flush()
            for line in rd:
                if line.strip():
                    wr.write(json.dumps(execute(client, lock, out_dir, line, extra), ensure_ascii=False) + "\n")
                    wr.flush()
    except OSError:
        pass


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="directory for screenshots")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if len(token) < 16:
        raise SystemExit("token must be at least 16 characters")
    out_dir = Path(args.out)
    lock = threading.Lock()
    from ..apps.keepassxc_guest import GuestKeePassXC  # imported lazily: only the guest needs it

    extra = GuestKeePassXC().handlers()
    with DesktopClient(out_dir) as client, socket.create_server((args.host, args.port)) as server:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=serve_connection, args=(conn, client, lock, out_dir, token, extra),
                             daemon=True).start()


if __name__ == "__main__":
    main()
