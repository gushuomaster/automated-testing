"""Desktop execution service: JSON-lines RPC over stdin/stdout.

    python -m testing_platform.autotest.desktop.service --out DIR

Request:  {"id": 1, "op": "observe", "args": {...}}
Response: {"id": 1, "ok": true, "result": {...}}  or  {"id": 1, "ok": false, "error": "...", "kind": "Refused"}

Runs in its own process so a hung UIA/COM call can be killed by the client without
taking down the agent.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import traceback

OPS = {"ping", "set_target", "focus", "observe", "click_element", "click_point", "type_text",
       "press_keys", "scroll", "drag", "set_value", "invoke", "wait"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="directory for screenshots")
    args = parser.parse_args(argv)

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware, before any UI import
    protocol = sys.stdout
    sys.stdout = sys.stderr  # libraries must not write into the protocol stream

    from .driver import Driver, Refused

    driver = Driver(args.out)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            op = req["op"]
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}")
            if op == "ping":
                result = {"pong": True}
            elif op == "set_target":
                result = driver.set_target(**req.get("args", {}))
            else:
                result = getattr(driver, op)(**req.get("args", {}))
            resp = {"id": req_id, "ok": True, "result": result}
        except Refused as exc:
            resp = {"id": req_id, "ok": False, "kind": "Refused", "error": str(exc)}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            resp = {"id": req_id, "ok": False, "kind": type(exc).__name__, "error": str(exc)}
        protocol.write(json.dumps(resp, ensure_ascii=False) + "\n")
        protocol.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
