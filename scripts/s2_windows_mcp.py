"""Bounded JSONL adapter for the pinned Windows-MCP UIA subpackage.

Organizer-owned config: source_root (the upstream src directory), hwnd, pid,
log_dir (absolute paths), deadline_utc (aware ISO UTC), max_inputs <= 30, role
test|organizer, safe_invoke_names (optional exact labels: 清空, 清除筛选).
The organizer freezes this config; requests cannot extend its permissions.
Each log_dir is single-use, including after exit or failed initialization.
Requests: observe; act(token,index,action[,value]);
ack(outcome=CONFIRMED|UNRESOLVED,reason). No business files are read.

Native return values are evidence only. Semantic acknowledgements belong to the
agent and require independent review after locking the run. Upstream GetPattern
swallows COMError; a missing pattern therefore remains explicitly ambiguous.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import re
import sys
import time
import uuid


PATTERNS = {
    "invoke": ("InvokePattern", "Invoke"),
    "set_value": ("ValuePattern", "SetValue"),
    "select": ("SelectionItemPattern", "Select"),
    "expand": ("ExpandCollapsePattern", "Expand"),
    "collapse": ("ExpandCollapsePattern", "Collapse"),
    "close": ("WindowPattern", "Close"),
}
DANGEROUS = re.compile(
    r"保存|删除|提交|支付|付款|导出|退出|关闭|清空|清除|重置|确认|确定|应用|完成|上传|发送|"
    r"下单|购买|发布|注销|卸载|覆盖|移除|新建|创建|添加|新增|导入|安装|启动|执行|运行|"
    r"save|delete|submit|pay|export|exit|close|clear|reset|confirm|apply|finish|"
    r"upload|send|purchase|publish|logout|uninstall|overwrite|remove|create|add|"
    r"import|install|launch|execute|run|\bok\b",
    re.IGNORECASE,
)


def utc_now():
    return datetime.now(timezone.utc)


class Denied(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def load_uia(source_root):
    """Import the existing implementation, without starting its MCP server."""
    if sys.version_info < (3, 14):
        raise ValueError("Windows-MCP pinned UIA requires Python >= 3.14")
    sys.path.insert(0, str(source_root))
    return importlib.import_module("windows_mcp.uia")


class Session:
    def __init__(self, config, uia=None, now=utc_now, monotonic=time.monotonic):
        self.now, self.monotonic = now, monotonic
        for key in ("source_root", "log_dir"):
            if not isinstance(config.get(key), str) or not Path(config[key]).is_absolute():
                raise ValueError(f"{key} must be an absolute path")
        for key in ("hwnd", "pid"):
            if type(config.get(key)) is not int or config[key] <= 0:
                raise ValueError(f"{key} must be a positive integer")
        self.hwnd, self.pid = config["hwnd"], config["pid"]
        self.role = config.get("role", "test")
        self.max_inputs = config.get("max_inputs", 30)
        if self.role not in {"test", "organizer"}:
            raise ValueError("role must be test or organizer")
        if type(self.max_inputs) is not int or not 1 <= self.max_inputs <= 30:
            raise ValueError("max_inputs must be 1..30")
        safe_names = config.get("safe_invoke_names", [])
        if not isinstance(safe_names, list) or any(
            not isinstance(name, str) or name not in {"清空", "清除筛选"}
            for name in safe_names
        ):
            raise ValueError("safe_invoke_names must be an exact-label list of 清空/清除筛选")
        self.safe_invoke_names = frozenset(safe_names)
        self.deadline = datetime.fromisoformat(config["deadline_utc"].replace("Z", "+00:00"))
        if self.deadline.utcoffset() != timedelta(0):
            raise ValueError("deadline_utc must use UTC")
        remaining = (self.deadline - now()).total_seconds()
        if not 0 < remaining <= 900:
            raise ValueError("deadline must be within the next 900 seconds")
        self.monotonic_deadline = monotonic() + remaining
        self.inputs = 0
        self.state = "READY"
        self.token = None
        self.controls = []
        self.nodes = []
        log_dir = Path(config["log_dir"])
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"events-{uuid.uuid4().hex}.jsonl"
        # Atomic, persistent claim: closing/crashing a worker never restores its
        # budget. Only the organizer can supply a different frozen run log_dir.
        self.marker_path = log_dir / "session.json"
        try:
            marker = self.marker_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise ValueError("log_dir already claimed; session restart is forbidden") from exc
        with marker:
            marker.write(json.dumps({"utc": self.now().isoformat(),
                                     "events": self.log_path.name, "config": config},
                                    ensure_ascii=False) + "\n")
        self.log = self.log_path.open("x", encoding="utf-8", newline="\n")
        try:
            self._event("session", config=config)
            self.uia = uia if uia is not None else load_uia(config["source_root"])
        except Exception:
            self.log.close()
            raise

    def _event(self, kind, **fields):
        self.log.write(json.dumps({"utc": self.now().isoformat(), "event": kind,
                                   "inputs_attempted": self.inputs, **fields},
                                  ensure_ascii=False) + "\n")
        self.log.flush()

    def _root(self):
        root = self.uia.ControlFromHandle(self.hwnd)
        if root is None or root.NativeWindowHandle != self.hwnd or root.ProcessId != self.pid:
            raise Denied("TARGET_MISMATCH", "Configured HWND/PID is not the current root")
        return root

    @staticmethod
    def _read(obj, attr, errors, field=None):
        try:
            return getattr(obj, attr)
        except Exception as exc:
            errors[field or attr] = f"{type(exc).__name__}: {exc}"
            return None

    def _pattern(self, control, name, errors):
        try:
            return control.GetPattern(getattr(self.uia.PatternId, name))
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return None

    def snapshot(self):
        # Invalidate old object/index bindings even when the next read fails.
        self.token = uuid.uuid4().hex
        self.controls, self.nodes = [], []
        errors, truncated = [], False
        try:
            stack = [(self._root(), None, 0)]
            visited = 0
            while stack and visited < 300:
                control, parent, depth = stack.pop()
                visited += 1
                try:
                    pid = control.ProcessId
                except Exception as exc:
                    errors.append({"parent": parent, "field": "ProcessId",
                                   "error": f"{type(exc).__name__}: {exc}"})
                    continue
                if pid != self.pid:
                    errors.append({"parent": parent, "field": "ProcessId",
                                   "error": "foreign_pid_subtree_excluded"})
                    continue
                index = len(self.nodes)
                field_errors = {}
                node = {"index": index, "parent": parent}
                for field, attr in (("name", "Name"), ("automation_id", "AutomationId"),
                                    ("control_type", "ControlTypeName"),
                                    ("focused", "HasKeyboardFocus"),
                                    ("enabled", "IsEnabled"), ("offscreen", "IsOffscreen")):
                    node[field] = self._read(control, attr, field_errors, field)
                node.update(value=None, selected=None, expanded_state=None,
                            available_actions=[], pattern_status={})
                focusable = self._read(control, "IsKeyboardFocusable", field_errors)
                if focusable is True:
                    node["available_actions"].append("focus")
                for name in ("InvokePattern", "ValuePattern", "SelectionItemPattern",
                             "ExpandCollapsePattern"):
                    pattern = self._pattern(control, name, field_errors)
                    node["pattern_status"][name] = (
                        "available" if pattern is not None else "unavailable_or_upstream_com_error")
                    if pattern is None:
                        continue
                    if name == "ValuePattern":
                        node["value"] = self._read(pattern, "Value", field_errors, "value")
                        readonly = self._read(pattern, "IsReadOnly", field_errors)
                        if readonly is False:
                            node["available_actions"].append("set_value")
                    elif name == "SelectionItemPattern":
                        node["selected"] = self._read(pattern, "IsSelected", field_errors, "selected")
                        node["available_actions"].append("select")
                    elif name == "ExpandCollapsePattern":
                        node["expanded_state"] = self._read(pattern, "ExpandCollapseState", field_errors)
                        node["available_actions"].extend(["expand", "collapse"])
                    else:
                        node["available_actions"].append("invoke")
                if self.role == "organizer" and index == 0:
                    pattern = self._pattern(control, "WindowPattern", field_errors)
                    if pattern is not None:
                        node["available_actions"].append("close")
                node["errors"] = field_errors
                self.nodes.append(node)
                self.controls.append(control)
                try:
                    children = control.GetChildren()
                    if depth < 12:
                        stack.extend((child, index, depth + 1) for child in reversed(children))
                    elif children:
                        truncated = True
                except Exception as exc:
                    node["errors"]["children"] = f"{type(exc).__name__}: {exc}"
            truncated = truncated or bool(stack)
        except Exception as exc:
            errors.append({"field": "root", "error": f"{type(exc).__name__}: {exc}"})
        status = "TOOL_BLOCKED" if not self.nodes else (
            "PARTIAL" if errors or any(n["errors"] for n in self.nodes) else "OK")
        return {"token": self.token, "status": status, "nodes": self.nodes,
                "errors": errors, "truncated": truncated}

    def _budget(self):
        if self.now() >= self.deadline or self.monotonic() >= self.monotonic_deadline:
            raise Denied("DEADLINE_EXCEEDED", "No further input permitted")
        if self.inputs >= self.max_inputs:
            raise Denied("INPUT_BUDGET_EXCEEDED", "No further input permitted")

    def _act(self, request):
        if self.state != "READY":
            raise Denied("REVIEW_REQUIRED" if self.state != "STOPPED" else "STOPPED",
                         "A reasoned acknowledgement is required before another input")
        action = request.get("action")
        if action not in {*PATTERNS, "focus"}:
            raise Denied("UNSUPPORTED_ACTION", "Only native bounded UIA actions are supported")
        if request.get("token") != self.token or self.token is None:
            raise Denied("STALE_TOKEN", "Use the token from the latest snapshot")
        index = request.get("index")
        if type(index) is not int or not 0 <= index < len(self.controls):
            raise Denied("INVALID_INDEX", "Index is outside the latest snapshot")
        self._root()
        control, node = self.controls[index], self.nodes[index]
        if control.ProcessId != self.pid:
            raise Denied("TARGET_MISMATCH", "Control PID changed")
        if action == "close" and (self.role != "organizer" or index != 0):
            raise Denied("POLICY_DENIED", "Close is restricted to organizer and bound root")
        if action == "invoke":
            name = control.Name  # Policy checks the current visible label, not an old cache.
            if (not isinstance(name, str) or not name.strip() or
                    (DANGEROUS.search(name) and name not in self.safe_invoke_names)):
                raise Denied("POLICY_DENIED", "Invocation may persist data or close the application")
        if action not in node["available_actions"]:
            raise Denied("PATTERN_UNAVAILABLE", "Requested action was not exposed by UIA")
        if control.IsEnabled is not True or control.IsOffscreen is not False:
            raise Denied("CONTROL_UNAVAILABLE", "Enabled/onscreen state must be explicit")
        if action == "set_value" and not isinstance(request.get("value"), str):
            raise Denied("INVALID_VALUE", "set_value requires a string (empty is allowed)")
        if action == "focus":
            callback, args = control.SetFocus, ()
        else:
            pattern_name, method = PATTERNS[action]
            pattern = control.GetPattern(getattr(self.uia.PatternId, pattern_name))
            if pattern is None:
                raise Denied("PATTERN_UNAVAILABLE", "Pattern absent or upstream swallowed COMError")
            if action == "set_value" and pattern.IsReadOnly is not False:
                raise Denied("CONTROL_UNAVAILABLE", "Value is not explicitly writable")
            callback = getattr(pattern, method)
            args = (request["value"],) if action == "set_value" else ()
        self._budget()  # Check immediately before the single native input, never retry.
        self.inputs += 1
        self.state = "NEEDS_REVIEW"
        self._event("input_started", request=request)
        try:
            native_return = callback(*args)
            status = "ACTION_RETURNED" if native_return is not False else "ACTION_FAILED"
            error = None
        except Exception as exc:
            native_return, status = None, "TOOL_BLOCKED"
            error = f"{type(exc).__name__}: {exc}"
        return {"status": status, "native_return": native_return, "error": error,
                "snapshot": self.snapshot(), "outcome": "NEEDS_REVIEW"}

    def _dispatch(self, request):
        if not isinstance(request, dict):
            raise Denied("INVALID_REQUEST", "Request must be one JSON object")
        op = request.get("op")
        if op == "observe":
            if self.state == "NEEDS_REVIEW":
                raise Denied("REVIEW_REQUIRED", "Acknowledge UNRESOLVED before passive review")
            if self.state == "PASSIVE_REVIEW":
                raise Denied("PASSIVE_LIMIT", "Only one passive observation is allowed")
            result = {"status": "OBSERVED", "snapshot": self.snapshot()}
            if self.state == "AWAIT_PASSIVE":
                self.state = "PASSIVE_REVIEW"
            return result
        if op == "act":
            return self._act(request)
        if op == "ack":
            reason, outcome = request.get("reason"), request.get("outcome")
            if not isinstance(reason, str) or not reason.strip():
                raise Denied("REASON_REQUIRED", "Semantic review requires an explicit reason")
            if outcome not in {"CONFIRMED", "UNRESOLVED"}:
                raise Denied("INVALID_OUTCOME", "Outcome must be CONFIRMED or UNRESOLVED")
            if self.state not in {"NEEDS_REVIEW", "PASSIVE_REVIEW"}:
                raise Denied("INVALID_ACK_STATE", "No action/passive result awaits review")
            self.state = ("READY" if outcome == "CONFIRMED" else
                          "STOPPED" if self.state == "PASSIVE_REVIEW" else "AWAIT_PASSIVE")
            return {"status": "ACKNOWLEDGED", "outcome": outcome, "reason": reason,
                    "semantic_authority": "agent_claim_requires_independent_review"}
        raise Denied("UNSUPPORTED_REQUEST", "Only observe, act and ack are supported")

    def handle(self, request):
        self._event("request", request=request)
        try:
            response = self._dispatch(request)
        except Denied as exc:
            response = {"status": exc.code, "error": str(exc)}
        except Exception as exc:
            response = {"status": "TOOL_BLOCKED", "error": f"{type(exc).__name__}: {exc}"}
        response.update(state=self.state, inputs_attempted=self.inputs)
        self._event("response", request=request, response=response)
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    protocol_stdout = sys.stdout
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        with redirect_stdout(sys.stderr):
            session = Session(config)
    except Exception as exc:
        print(json.dumps({"status": "INITIALIZATION_BLOCKED", "error":
                          f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
        return 1
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                response = {"status": "INVALID_JSON", "error": str(exc)}
                session._event("invalid_request", raw_request=line, response=response)
            else:
                with redirect_stdout(sys.stderr):
                    response = session.handle(request)
            print(json.dumps(response, ensure_ascii=False), file=protocol_stdout, flush=True)
    finally:
        session.log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
