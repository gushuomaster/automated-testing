from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from testing_platform.autotest.agent import (
    Agent, Budget, ToolInputError, parse_finish, to_service_call,
)
from testing_platform.autotest.apps.keepassxc import parse_export
from testing_platform.autotest.checks import collateral_changes, evaluate, numbers_in
from testing_platform.autotest.desktop.client import DesktopClient, ServiceError, ToolTimeout
from testing_platform.autotest.desktop.observation import (
    Element, Frame, escape_text, format_element, format_observation, keep_element, scale_for,
)
from testing_platform.autotest.model import Usage


# ---- observation helpers -----------------------------------------------------------------

def test_scale_for_limits_edge_and_pixels():
    assert scale_for(1200, 900) == 1.0
    s = scale_for(3200, 1000)
    assert round(3200 * s) <= 1568
    s = scale_for(1500, 1500)
    assert 1500 * s * 1500 * s <= 1_150_001


def test_frame_roundtrip_with_negative_origin():
    frame = Frame(left=3229, top=-519, scale=0.5)
    assert frame.to_image(3229 + 200, -519 + 100) == (100, 50)
    assert frame.to_screen(100, 50) == (3429, -419)


def test_format_element_hides_password_and_reports_state():
    frame = Frame(0, 0, 1.0)
    el = Element(id="e3", hwnd=1, path=[0], control_type="Edit", value="secret", is_password=True,
                 rect=[0, 0, 100, 20], focused=True)
    text = format_element(el, frame)
    assert "secret" not in text and "(password field)" in text and "focused" in text
    box = Element(id="e4", hwnd=1, path=[1], control_type="CheckBox", name="显示", toggle=1, rect=[10, 10, 30, 30])
    assert format_element(box, frame) == '[e4] CheckBox "显示" (checked) @(20,20)'


def test_keep_element_filters_unnamed_containers_and_zero_size():
    assert keep_element("Button", "", None, [0, 0, 10, 10])
    assert not keep_element("Pane", "", None, [0, 0, 10, 10])
    assert keep_element("Text", "标签", None, [0, 0, 10, 10])
    assert not keep_element("Button", "x", None, [0, 0, 0, 10])


def test_escape_text_protects_pywinauto_specials():
    assert escape_text("Abc#12345") == "Abc#12345"
    assert escape_text("a+b^c%d~(e)") == "a{+}b{^}c{%}d{~}{(}e{)}"
    assert escape_text("x{y}") == "x{{}y{}}"


def test_format_observation_marks_foreground_and_disabled_windows():
    obs = {"frame": {"left": 0, "top": 0, "scale": 1.0}, "truncated": True,
           "windows": [{"title": "对话框", "foreground": True}, {"title": "主窗口", "enabled": False}],
           "elements": [Element(id="e1", hwnd=1, path=[0], control_type="Button", name="确定",
                                rect=[0, 0, 10, 10]).to_dict()]}
    text = format_observation(obs)
    assert '"对话框" [前台]' in text and "被模态框阻挡" in text and "[e1] Button" in text and "截断" in text


# ---- tool validation -----------------------------------------------------------------------

def test_to_service_call_maps_and_validates():
    assert to_service_call("click", {"element_id": "e2"})[0] == "click_element"
    assert to_service_call("click", {"x": 5, "y": 6, "double": True}) == (
        "click_point", {"x": 5.0, "y": 6.0, "button": "left", "double": True})
    assert to_service_call("scroll", {"x": 1, "y": 2, "amount": -99})[1]["amount"] == -20
    assert to_service_call("wait", {"seconds": 60})[1]["seconds"] == 10.0
    assert to_service_call("drag", {"from_element_id": "e1", "to_x": 3, "to_y": 4}) == (
        "drag", {"from_element_id": "e1", "to_x": 3.0, "to_y": 4.0})
    with pytest.raises(ToolInputError):
        to_service_call("drag", {"from_element_id": "e1", "to_x": 3})
    for name, args in [("click", {}), ("click", {"x": 1}), ("click", {"element_id": "e1", "button": "middle"}),
                       ("type_text", {"text": ""}), ("scroll", {"x": 1, "y": 1, "amount": 0}),
                       ("press_keys", {}), ("set_value", {"element_id": "e1"}), ("nope", {})]:
        with pytest.raises(ToolInputError):
            to_service_call(name, args)


def test_parse_finish_requires_status_and_summary():
    assert parse_finish({"status": "completed", "summary": "ok"})["answer"] == ""
    with pytest.raises(ToolInputError):
        parse_finish({"status": "done", "summary": "ok"})
    with pytest.raises(ToolInputError):
        parse_finish({"status": "failed", "summary": " "})


# ---- agent loop with fakes -----------------------------------------------------------------

class Block(dict):
    def model_dump(self, exclude_none=True):
        return dict(self)


def tool(name, args, n=[0]):
    n[0] += 1
    return Block(type="tool_use", id=f"tu{n[0]}", name=name, input=args)


class FakeModel:
    model = "claude-opus-5-5"
    effort = "medium"

    def __init__(self, turns):
        self.turns = list(turns)
        self.usage = Usage()
        self.requests = []

    def create(self, system, messages, tools):
        self.requests.append(json.loads(json.dumps(messages, default=str)))
        content, stop = self.turns.pop(0)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        self.usage.add(usage)
        return SimpleNamespace(content=content, stop_reason=stop, usage=Block(input_tokens=10))


class FakeDesktop:
    def __init__(self, png, fail_ops=()):
        self.png = png
        self.calls = []
        self.fail_ops = fail_ops

    def call(self, op, timeout=None, **args):
        self.calls.append((op, args))
        if op in self.fail_ops:
            raise ServiceError("Refused", "not target")
        if op == "observe":
            return {"frame": {"left": 0, "top": 0, "scale": 1.0}, "windows": [{"title": "App", "foreground": True}],
                    "elements": [], "truncated": False, "annotated": str(self.png), "screenshot": str(self.png)}
        return {}


@pytest.fixture
def png(tmp_path):
    from PIL import Image
    path = tmp_path / "obs.png"
    Image.new("RGB", (4, 4)).save(path)
    return path


def test_agent_action_then_finish(tmp_path, png):
    model = FakeModel([
        ([Block(type="text", text="点确定"), tool("click", {"element_id": "e1"})], "tool_use"),
        ([tool("finish", {"status": "completed", "answer": "3", "summary": "看到 3 条"})], "tool_use"),
    ])
    desktop = FakeDesktop(png)
    result = Agent(model, desktop, tmp_path).run("数条目")
    assert result.outcome == "completed" and result.answer == "3" and result.actions == 1
    assert [c[0] for c in desktop.calls] == ["observe", "click_element", "observe"]
    last_user = model.requests[1][-1]["content"]
    assert last_user[0]["type"] == "tool_result"
    assert any(c.get("type") == "image" for c in last_user[0]["content"])
    assert (tmp_path / "steps.jsonl").exists()


def test_agent_rejects_finish_in_same_turn_as_action(tmp_path, png):
    model = FakeModel([
        ([tool("click", {"element_id": "e1"}), tool("finish", {"status": "completed", "summary": "x"})], "tool_use"),
        ([tool("finish", {"status": "completed", "summary": "确认"})], "tool_use"),
    ])
    result = Agent(model, FakeDesktop(png), tmp_path).run("t")
    assert result.outcome == "completed" and result.model_calls == 2


def test_agent_skips_rest_of_turn_after_refused_action(tmp_path, png):
    model = FakeModel([
        ([tool("click", {"x": 1, "y": 1}), tool("press_keys", {"keys": "^s"})], "tool_use"),
        ([tool("finish", {"status": "failed", "summary": "拒绝"})], "tool_use"),
    ])
    desktop = FakeDesktop(png, fail_ops=("click_point",))
    result = Agent(model, desktop, tmp_path).run("t")
    assert result.refused == 1 and result.actions == 1
    assert "press_keys" not in [c[0] for c in desktop.calls]


def test_agent_budget_exhaustion_allows_only_finish(tmp_path, png):
    model = FakeModel([
        ([tool("press_keys", {"keys": "a"})], "tool_use"),
        ([tool("press_keys", {"keys": "b"})], "tool_use"),
        ([tool("press_keys", {"keys": "c"})], "tool_use"),
    ])
    result = Agent(model, FakeDesktop(png), tmp_path, budget=Budget(max_actions=2)).run("t")
    assert result.outcome == "budget_actions" and result.actions == 2


def test_agent_budget_final_finish_is_recorded(tmp_path, png):
    model = FakeModel([
        ([tool("press_keys", {"keys": "a"})], "tool_use"),
        ([tool("finish", {"status": "failed", "summary": "没做完"})], "tool_use"),
    ])
    result = Agent(model, FakeDesktop(png), tmp_path, budget=Budget(max_actions=1)).run("t")
    assert result.outcome == "failed" and result.error == "budget_actions"


def test_agent_stops_when_model_never_finishes(tmp_path, png):
    model = FakeModel([([Block(type="text", text="好了")], "end_turn"), ([Block(type="text", text="嗯")], "end_turn")])
    result = Agent(model, FakeDesktop(png), tmp_path).run("t")
    assert result.outcome == "no_finish" and result.model_calls == 2


def test_agent_stops_on_refusal(tmp_path, png):
    model = FakeModel([([], "refusal")])
    assert Agent(model, FakeDesktop(png), tmp_path).run("t").outcome == "refusal"


# ---- ground truth parsing and checks --------------------------------------------------------

XML = """<?xml version="1.0" encoding="UTF-8"?>
<KeePassFile><Meta><RecycleBinUUID>BIN=</RecycleBinUUID></Meta><Root><Group><UUID>R=</UUID><Name>密码</Name>
<Group><UUID>W=</UUID><Name>工作</Name>
  <Entry><String><Key>Title</Key><Value>VPN</Value></String><String><Key>UserName</Key><Value>lisi</Value></String>
    <String><Key>Password</Key><Value>Vpn#2026pwd</Value></String>
    <History><Entry><String><Key>Title</Key><Value>VPN</Value></String><String><Key>UserName</Key><Value>zhangsan</Value></String></Entry></History>
  </Entry>
</Group>
<Group><UUID>BIN=</UUID><Name>回收站</Name>
  <Entry><String><Key>Title</Key><Value>测试服务器</Value></String></Entry>
</Group>
</Group></Root></KeePassFile>"""


def test_parse_export_skips_recycle_bin_and_history():
    snap = parse_export("输入密码：" + XML)
    assert snap.groups == {"工作"}
    assert snap.entries["工作/VPN"]["UserName"] == "lisi"
    assert snap.find_title("测试服务器") == []
    assert snap.entries_in("工作") == ["工作/VPN"]


def test_numbers_in_handles_chinese_and_digits():
    assert numbers_in("共 3 个条目") == {3}
    assert numbers_in("三个条目") == {3}


def test_evaluate_checks_and_collateral():
    snap = parse_export(XML)
    seed = parse_export(XML.replace("<Value>lisi</Value>", "<Value>zhangsan</Value>"))
    task = {"checks": [{"type": "entry_fields", "path": "工作/VPN", "fields": {"UserName": "lisi"}},
                       {"type": "entry_absent", "title": "测试服务器"}], "touches": ["工作/VPN"]}
    assert evaluate(task, snap, seed, None, "")["passed"]
    task["touches"] = []
    verdict = evaluate(task, snap, seed, None, "")
    assert not verdict["passed"] and verdict["collateral"] == ["entry changed: 工作/VPN (UserName)"]
    assert collateral_changes(seed, parse_export(XML.replace("<Name>工作</Name>", "<Name>X</Name>")), []) != []


def test_answer_number_rejects_competing_counts():
    task = {"checks": [{"type": "answer_number", "value": 3}]}
    assert evaluate(task, None, None, None, "共 3 个条目（2026 年）")["passed"]
    assert not evaluate(task, None, None, None, "3 个或 4 个")["passed"]


def test_config_check():
    from configparser import ConfigParser
    cfg = ConfigParser()
    cfg.optionxform = str
    cfg.read_string("[Security]\nLockDatabaseIdle=true\nLockDatabaseIdleSeconds=120\n")
    task = {"checks": [{"type": "config", "section": "Security",
                        "values": {"LockDatabaseIdle": "true", "LockDatabaseIdleSeconds": "120"}}]}
    assert evaluate(task, None, None, cfg, "")["passed"]
    cfg.set("Security", "LockDatabaseIdleSeconds", "240")
    assert not evaluate(task, None, None, cfg, "")["passed"]


# ---- client timeout / restart ---------------------------------------------------------------

FAKE_SERVICE = r"""
import json, sys, time
for line in sys.stdin:
    req = json.loads(line)
    if req["op"] == "slow":
        time.sleep(30)
    if req["op"] == "die":
        sys.exit(1)
    print(json.dumps({"id": req["id"], "ok": req["op"] != "bad", "result": {"op": req["op"]},
                      "kind": "Refused", "error": "nope"}), flush=True)
"""


def test_client_timeout_restarts_service(tmp_path):
    client = DesktopClient(tmp_path, command=[sys.executable, "-c", FAKE_SERVICE])
    with client:
        assert client.call("ping") == {"op": "ping"}
        with pytest.raises(ToolTimeout):
            client.call("slow", timeout=1)
        assert client.restarts == 1
        assert client.call("ping", timeout=10) == {"op": "ping"}
        with pytest.raises(ServiceError) as err:
            client.call("bad")
        assert err.value.kind == "Refused"
        with pytest.raises(ServiceError):
            client.call("die", timeout=10)
        assert client.call("ping", timeout=10) == {"op": "ping"}
