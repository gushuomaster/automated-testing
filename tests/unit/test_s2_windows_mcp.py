from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "s2_windows_mcp", Path(__file__).resolve().parents[2] / "scripts/s2_windows_mcp.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Pattern:
    Value = ""
    IsReadOnly = False
    IsSelected = False
    ExpandCollapseState = 0

    def __init__(self, control):
        self.control = control

    def _call(self, action, *args):
        self.control.calls.append((action, args))
        if self.control.failure:
            raise RuntimeError("fake native input failure")
        if action == "set_value":
            self.Value = args[0]
        if action == "select":
            self.IsSelected = True
        return self.control.native_return

    def Invoke(self):
        return self._call("invoke")

    def SetValue(self, value):
        return self._call("set_value", value)

    def Select(self):
        return self._call("select")

    def Expand(self):
        return self._call("expand")

    def Collapse(self):
        return self._call("collapse")

    def Close(self):
        return self._call("close")


class Control:
    ProcessId = 100
    NativeWindowHandle = 50
    Name = "查看"
    AutomationId = "neutral"
    ControlTypeName = "EditControl"
    HasKeyboardFocus = False
    IsKeyboardFocusable = True
    IsEnabled = True
    IsOffscreen = False
    native_return = True
    failure = False

    def __init__(self, children=()):
        self.children = list(children)
        self.calls = []
        self.pattern = Pattern(self)
        self.patterns = {name: self.pattern for name in (
            "InvokePattern", "ValuePattern", "SelectionItemPattern",
            "ExpandCollapsePattern", "WindowPattern")}

    def GetChildren(self):
        return self.children

    def GetPattern(self, name):
        return self.patterns.get(name)

    def SetFocus(self):
        self.calls.append(("focus", ()))
        if self.failure:
            raise RuntimeError("fake focus failure")
        self.HasKeyboardFocus = self.native_return
        return self.native_return


class UIA:
    PatternId = SimpleNamespace(**{name: name for name in (
        "InvokePattern", "ValuePattern", "SelectionItemPattern",
        "ExpandCollapsePattern", "WindowPattern")})

    def __init__(self, root):
        self.root = root
        self.handles = []

    def ControlFromHandle(self, hwnd):
        self.handles.append(hwnd)
        return self.root


@pytest.fixture
def make_session(tmp_path):
    sessions = []

    def create(root=None, **options):
        root = root or Control()
        clock = SimpleNamespace(wall=datetime.now(timezone.utc), mono=1.0)
        config = {"source_root": str(tmp_path / "upstream-src"), "hwnd": 50,
                  "pid": 100, "log_dir": str(tmp_path / f"logs-{len(sessions)}"),
                  "max_inputs": 30,
                  "deadline_utc": (clock.wall + timedelta(seconds=899)).isoformat(),
                  "role": "test", **options}
        session = MODULE.Session(config, UIA(root), now=lambda: clock.wall,
                                 monotonic=lambda: clock.mono)
        sessions.append(session)
        return session, root, clock

    yield create
    for session in sessions:
        session.log.close()


def observe(session):
    return session.handle({"op": "observe"})["snapshot"]


def act(session, snapshot, action="focus", index=0, **extra):
    return session.handle({"op": "act", "token": snapshot["token"],
                           "index": index, "action": action, **extra})


def ack(session, outcome="CONFIRMED"):
    return session.handle({"op": "ack", "outcome": outcome,
                           "reason": "根据最新字段回读作出的Agent语义判断，待独立审查"})


@pytest.mark.parametrize("field,value", [("ProcessId", 999), ("NativeWindowHandle", 99)])
def test_binding_rejects_wrong_hwnd_or_pid(make_session, field, value):
    session, root, _ = make_session()
    setattr(root, field, value)
    snapshot = observe(session)
    assert snapshot["status"] == "TOOL_BLOCKED"
    assert snapshot["nodes"] == []
    assert session.uia.handles == [50]
    assert root.calls == []


def test_foreign_pid_subtree_is_never_exported(make_session):
    foreign = Control([Control()])
    foreign.ProcessId, foreign.Name = 999, "do not export this"
    session, _, _ = make_session(Control([foreign, Control()]))
    snapshot = observe(session)
    assert len(snapshot["nodes"]) == 2
    assert snapshot["status"] == "PARTIAL"
    assert "do not export this" not in json.dumps(snapshot)


def test_token_indexes_and_actual_object_refresh(make_session):
    old_child, new_child = Control(), Control()
    session, root, _ = make_session(Control([old_child]))
    old = observe(session)
    root.children = [new_child]
    fresh = observe(session)
    assert act(session, old, index=1)["status"] == "STALE_TOKEN"
    assert act(session, fresh, index=-1)["status"] == "INVALID_INDEX"
    assert act(session, fresh, index=True)["status"] == "INVALID_INDEX"
    result = act(session, fresh, index=1)
    assert result["status"] == "ACTION_RETURNED"
    assert result["snapshot"]["token"] != fresh["token"]
    assert old_child.calls == []
    assert new_child.calls == [("focus", ())]


def test_budget_and_deadline_block_before_native_call(make_session):
    session, root, clock = make_session(max_inputs=1)
    first = act(session, observe(session))
    ack(session)
    assert act(session, first["snapshot"])["status"] == "INPUT_BUDGET_EXCEEDED"
    assert len(root.calls) == 1
    session2, root2, clock2 = make_session()
    snapshot = observe(session2)
    clock2.mono += 900
    # The monotonic cap also holds if the wall clock has not advanced.
    assert act(session2, snapshot)["status"] == "DEADLINE_EXCEEDED"
    assert root2.calls == []
    clock.wall += timedelta(seconds=900)
    assert act(session, first["snapshot"])["status"] == "DEADLINE_EXCEEDED"


@pytest.mark.parametrize("failure,returned,status", [
    (True, True, "TOOL_BLOCKED"), (False, False, "ACTION_FAILED"),
])
def test_failed_native_inputs_are_counted_and_need_review(make_session, failure, returned, status):
    session, root, _ = make_session()
    root.failure, root.native_return = failure, returned
    result = act(session, observe(session))
    assert result["status"] == status
    assert result["inputs_attempted"] == 1
    assert result["outcome"] == "NEEDS_REVIEW"
    assert result["snapshot"]["nodes"]
    assert act(session, result["snapshot"])["status"] == "REVIEW_REQUIRED"
    assert len(root.calls) == 1


def test_unconfirmed_inputs_and_unjustified_ack_rejected(make_session):
    session, root, _ = make_session()
    result = act(session, observe(session))
    assert act(session, result["snapshot"])["status"] == "REVIEW_REQUIRED"
    assert session.handle({"op": "observe"})["status"] == "REVIEW_REQUIRED"
    assert session.handle({"op": "ack", "outcome": "CONFIRMED", "reason": " "})[
        "status"] == "REASON_REQUIRED"
    assert len(root.calls) == 1


def test_passive_still_unresolved_permanently_stops_even_organizer_close(make_session):
    session, root, _ = make_session(role="organizer")
    result = act(session, observe(session))
    assert ack(session, "UNRESOLVED")["state"] == "AWAIT_PASSIVE"
    assert act(session, result["snapshot"], "close")["status"] == "REVIEW_REQUIRED"
    assert ack(session)["status"] == "INVALID_ACK_STATE"
    passive = observe(session)
    assert session.state == "PASSIVE_REVIEW"
    assert session.handle({"op": "observe"})["status"] == "PASSIVE_LIMIT"
    assert ack(session, "UNRESOLVED")["state"] == "STOPPED"
    assert act(session, passive, "close")["status"] == "STOPPED"
    assert ack(session)["status"] == "INVALID_ACK_STATE"
    assert observe(session)["nodes"]
    assert root.calls == [("focus", ())]


@pytest.mark.parametrize("passive", [False, True])
def test_semantic_confirmation_allows_next_input(make_session, passive):
    session, root, _ = make_session()
    result = act(session, observe(session))
    if passive:
        ack(session, "UNRESOLVED")
        snapshot = observe(session)
    else:
        snapshot = result["snapshot"]
    confirmation = ack(session)
    assert confirmation["state"] == "READY"
    assert "independent_review" in confirmation["semantic_authority"]
    assert act(session, snapshot, "select")["status"] == "ACTION_RETURNED"
    assert root.calls == [("focus", ()), ("select", ())]


@pytest.mark.parametrize("name", ["保存", "删除订单", "提交", "支付", "导出", "退出",
                                 "清空", "清除筛选", "Save As", "OK"])
def test_dangerous_invokes_never_input(make_session, name):
    session, root, _ = make_session()
    snapshot = observe(session)
    root.Name = name  # Re-read label immediately before invocation.
    assert act(session, snapshot, "invoke")["status"] == "POLICY_DENIED"
    assert root.calls == []
    assert session.inputs == 0


@pytest.mark.parametrize("name", ["清空", "清除筛选"])
def test_organizer_config_allows_only_exact_safe_invoke_names(make_session, name):
    session, root, _ = make_session(safe_invoke_names=[name])
    snapshot = observe(session)
    root.Name = name
    assert act(session, snapshot, "invoke")["status"] == "ACTION_RETURNED"
    assert root.calls == [("invoke", ())]
    assert session.inputs == 1


@pytest.mark.parametrize("name", ["清空", "清空筛选", "清空全部数据", "删除", "清空 ",
                                 "清除全部数据", "清除筛选 "])
def test_safe_invoke_does_not_broaden_policy_or_accept_request_override(make_session, name):
    session, root, _ = make_session(safe_invoke_names=[] if name == "清空" else ["清空"])
    snapshot = observe(session)
    root.Name = name
    result = act(session, snapshot, "invoke", safe_invoke_names=[name])
    assert result["status"] == "POLICY_DENIED"
    assert root.calls == []
    assert session.inputs == 0


@pytest.mark.parametrize("names", [None, "清空", ["删除"], ["清空筛选"], [1]])
def test_safe_invoke_config_rejects_nonexact_or_malformed_names(make_session, names):
    with pytest.raises(ValueError, match="safe_invoke_names"):
        make_session(safe_invoke_names=names)


@pytest.mark.parametrize("close_first", [False, True])
def test_log_dir_is_single_use_even_after_worker_exit(make_session, close_first):
    session, root, _ = make_session(max_inputs=1)
    act(session, observe(session))
    original = session.marker_path.read_bytes()
    if close_first:
        session.log.close()
    with pytest.raises(ValueError, match="session restart is forbidden"):
        make_session(log_dir=str(session.log_path.parent), max_inputs=30)
    assert session.marker_path.read_bytes() == original
    assert len(list(session.log_path.parent.glob("events-*.jsonl"))) == 1
    assert root.calls == [("focus", ())]


def test_failed_initialization_also_claims_log_dir(make_session, monkeypatch):
    session, _, _ = make_session()
    config = json.loads(session.marker_path.read_text(encoding="utf-8"))["config"]
    config["log_dir"] = str(session.log_path.parent / "failed-initialization")

    def failed_import(source_root):
        raise RuntimeError("fake UIA import failure")

    monkeypatch.setattr(MODULE, "load_uia", failed_import)
    with pytest.raises(RuntimeError, match="fake UIA import failure"):
        MODULE.Session(config)
    with pytest.raises(ValueError, match="session restart is forbidden"):
        MODULE.Session(config, UIA(Control()))
    assert (Path(config["log_dir"]) / "session.json").exists()


def test_empty_value_retained_and_focus_is_explicit_readback(make_session):
    session, root, _ = make_session()
    root.pattern.Value = "original"
    result = act(session, observe(session), "set_value", value="")
    node = result["snapshot"]["nodes"][0]
    assert node["value"] == ""
    assert node["focused"] is False
    assert result["outcome"] != "CONFIRMED"
    ack(session)
    focused = act(session, result["snapshot"])
    assert focused["snapshot"]["nodes"][0]["focused"] is True
    assert focused["outcome"] == "NEEDS_REVIEW"


def test_unreadable_focus_not_defaulted_to_true(make_session):
    class BrokenFocus(Control):
        @property
        def HasKeyboardFocus(self):
            raise RuntimeError("focus unavailable")

    session, _, _ = make_session(BrokenFocus())
    snapshot = observe(session)
    assert snapshot["status"] == "PARTIAL"
    assert snapshot["nodes"][0]["focused"] is None
    assert "focus unavailable" in snapshot["nodes"][0]["errors"]["focused"]


def test_missing_patterns_remain_ambiguous_and_unsupported_actions_rejected(make_session):
    session, root, _ = make_session()
    root.patterns = {}
    snapshot = observe(session)
    assert snapshot["nodes"][0]["value"] is None
    assert snapshot["nodes"][0]["pattern_status"]["ValuePattern"] == "unavailable_or_upstream_com_error"
    for action in ("click", "screenshot", "execute", "keyboard", "batch"):
        assert act(session, snapshot, action)["status"] == "UNSUPPORTED_ACTION"
    assert root.calls == []


def test_close_only_organizer_bound_root(make_session):
    session, _, _ = make_session()
    assert act(session, observe(session), "close")["status"] == "POLICY_DENIED"
    organizer, root, _ = make_session(Control([Control()]), role="organizer")
    snapshot = observe(organizer)
    assert act(organizer, snapshot, "close", index=1)["status"] == "POLICY_DENIED"
    assert act(organizer, snapshot, "close")["status"] == "ACTION_RETURNED"
    assert root.calls == [("close", ())]


def test_snapshot_limits_nodes_and_depth(make_session):
    session, _, _ = make_session(Control([Control() for _ in range(400)]))
    snapshot = observe(session)
    assert len(snapshot["nodes"]) == 300
    assert snapshot["truncated"] is True
    deep = Control()
    for _ in range(20):
        deep = Control([deep])
    session2, _, _ = make_session(deep)
    snapshot = observe(session2)
    assert len(snapshot["nodes"]) == 13
    assert snapshot["truncated"] is True


def test_log_is_unique_exact_utf8_request_and_response(make_session):
    session, _, _ = make_session()
    request = {"op": "observe", "note": "中文"}
    response = session.handle(request)
    records = [json.loads(line) for line in session.log_path.read_text(encoding="utf-8").splitlines()]
    assert records[1]["request"] == request
    assert records[2]["request"] == request
    assert records[2]["response"] == response
    assert records[2]["inputs_attempted"] == 0
    assert records[2]["utc"].endswith("+00:00")
    second, _, _ = make_session()
    assert second.log_path != session.log_path
    assert session.log_path.exists()
