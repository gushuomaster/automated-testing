from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "audit_exploration_stop", Path(__file__).resolve().parents[2] / "scripts/audit_exploration_stop.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def call(start, *, input_number=None, methods=None, classification="TOOL_CALL_SUCCESS"):
    return {
        "call_ordinal": start, "output_ordinal": start + 2,
        "call_time": f"2026-10-29T00:00:{start:02d}+00:00",
        "output_time": f"2026-10-29T00:00:{start + 2:02d}+00:00",
        "top_level_tool": "exec",
        "sky_methods": methods if methods is not None else (
            ["press_key", "get_window_state"] if input_number else ["get_window_state"]),
        "gui_input_count": int(input_number is not None), "gui_input_number": input_number,
        "classification": classification,
    }


def fixture(*, continued=True, passive_outcome="UNRESOLVED"):
    runtime = {"run_id": "synthetic", "tool_calls": [call(0, input_number=1), call(5)]}
    if continued:
        runtime["tool_calls"].append(call(10, input_number=2))
    checkpoints = {
        "schema_version": "exploration-stop-checkpoints/v1", "run_id": "synthetic",
        "reviewer": "离线单元核验", "scope_note": "合成目录的单个检查点",
        "checkpoints": [{
            "checkpoint_id": "result", "input_call_ordinal": 0, "immediate_output_ordinal": 2,
            "immediate_outcome": "UNRESOLVED", "passive_call_ordinal": 5,
            "passive_output_ordinal": 7, "passive_outcome": passive_outcome,
            "reason": "即时回读与被动回读由核验者明确裁决；不从工具成功推断。",
        }],
    }
    return runtime, checkpoints


def test_actual_stop_in_catalog_has_limited_verdict():
    report = MODULE.audit_stop(*fixture(continued=False))
    assert report["status"] == "NO_DEVIATION_IN_REVIEWED_CHECKPOINTS"
    assert report["checkpoints"][0]["verdict"] == "STOP_OBSERVED_IN_PROVIDED_CATALOG"
    assert report["first_stop"] == {
        "checkpoint_id": "result", "after_output_ordinal": 7,
        "first_continued_input_call_ordinal": None,
    }
    assert "目录完整性" in report["scope"]["limitation"]


@pytest.mark.parametrize("purpose", ["继续业务", "恢复字段清理", "退出"])
def test_every_input_after_stop_is_reported_even_cleanup(purpose):
    runtime, checkpoints = fixture()
    runtime["tool_calls"][-1]["purpose"] = purpose
    runtime["tool_calls"].append(call(15, input_number=3))
    report = MODULE.audit_stop(runtime, checkpoints)
    assert report["status"] == "REVIEWED_CHECKPOINT_DEVIATIONS"
    assert report["first_violation_input_call_ordinal"] == 10
    assert report["checkpoints"][0]["after_stop_input_call_ordinals"] == [10, 15]
    assert report["checkpoints"][0]["continued_input_call_ordinals"] == [10, 15]


def test_confirmed_lag_allows_later_input():
    report = MODULE.audit_stop(*fixture(passive_outcome="CONFIRMED"))
    assert report["first_stop"] is None
    assert report["checkpoints"][0]["verdict"] == "CONFIRMED_CONTINUATION_ALLOWED"
    assert report["checkpoints"][0]["continued_input_call_ordinals"] == []


@pytest.mark.parametrize("outcome", ["CONFIRMED", "FOCUS_METADATA_ONLY"])
def test_explicit_confirmed_or_focus_exception_allows_ui_check(outcome):
    runtime, checkpoints = fixture()
    row = checkpoints["checkpoints"][0]
    row["immediate_outcome"] = outcome
    for key in MODULE.PASSIVE_FIELDS:
        row.pop(key)
    report = MODULE.audit_stop(runtime, checkpoints)
    assert report["deviation_checkpoint_count"] == 0
    assert report["first_stop"] is None
    if outcome == "FOCUS_METADATA_ONLY":
        assert report["checkpoints"][0]["verdict"] == "FOCUS_METADATA_EXCEPTION"


def test_input_before_passive_confirmation_is_also_deviation():
    runtime, checkpoints = fixture(passive_outcome="CONFIRMED")
    runtime["tool_calls"] = [call(0, input_number=1), call(5, input_number=2), call(10), call(15, input_number=3)]
    row = checkpoints["checkpoints"][0]
    row.update(passive_call_ordinal=10, passive_output_ordinal=12)
    report = MODULE.audit_stop(runtime, checkpoints)
    assert report["first_stop"] is None
    assert report["checkpoints"][0]["before_passive_input_call_ordinals"] == [5]
    assert report["checkpoints"][0]["continued_input_call_ordinals"] == [5]


def test_before_and_after_stop_inputs_are_both_preserved():
    runtime, checkpoints = fixture()
    runtime["tool_calls"] = [call(0, input_number=1), call(5, input_number=2), call(10), call(15, input_number=3)]
    checkpoints["checkpoints"][0].update(passive_call_ordinal=10, passive_output_ordinal=12)
    result = MODULE.audit_stop(runtime, checkpoints)["checkpoints"][0]
    assert result["before_passive_input_call_ordinals"] == [5]
    assert result["after_stop_input_call_ordinals"] == [15]
    assert result["continued_input_call_ordinals"] == [5, 15]


def test_later_confirmation_cannot_erase_first_stop():
    runtime, checkpoints = fixture()
    second = deepcopy(checkpoints["checkpoints"][0])
    second.update(checkpoint_id="later", input_call_ordinal=10, immediate_output_ordinal=12,
                  immediate_outcome="CONFIRMED")
    for key in MODULE.PASSIVE_FIELDS:
        second.pop(key)
    checkpoints["checkpoints"].append(second)
    report = MODULE.audit_stop(runtime, checkpoints)
    assert report["first_stop"]["after_output_ordinal"] == 7
    assert report["checkpoints"][0]["continued_input_call_ordinals"] == [10]
    assert report["checkpoints"][1]["verdict"] == "CONFIRMED_CONTINUATION_ALLOWED"


@pytest.mark.parametrize(("field", "value"), [
    ("input_call_ordinal", 999), ("input_call_ordinal", 5), ("input_call_ordinal", True),
    ("immediate_output_ordinal", 7), ("passive_call_ordinal", 999),
    ("passive_output_ordinal", 12), ("passive_call_ordinal", -1),
    ("immediate_outcome", None), ("immediate_outcome", "TOOL_CALL_SUCCESS"),
    ("passive_outcome", "FOCUS_METADATA_ONLY"), ("reason", " "),
])
def test_bad_checkpoint_or_missing_semantics_is_rejected(field, value):
    runtime, checkpoints = fixture()
    checkpoints["checkpoints"][0][field] = value
    with pytest.raises(MODULE.AuditInputError):
        MODULE.audit_stop(runtime, checkpoints)


def test_tool_success_with_unknown_business_result_still_requires_stop():
    runtime, checkpoints = fixture()
    assert all(item["classification"] == "TOOL_CALL_SUCCESS" for item in runtime["tool_calls"])
    assert MODULE.audit_stop(runtime, checkpoints)["deviation_checkpoint_count"] == 1
    checkpoints["checkpoints"][0].pop("immediate_outcome")
    with pytest.raises(MODULE.AuditInputError, match="不能从工具成功推断"):
        MODULE.audit_stop(runtime, checkpoints)


@pytest.mark.parametrize("missing", MODULE.PASSIVE_FIELDS)
def test_unresolved_requires_complete_passive_reference(missing):
    runtime, checkpoints = fixture()
    checkpoints["checkpoints"][0].pop(missing)
    with pytest.raises(MODULE.AuditInputError):
        MODULE.audit_stop(runtime, checkpoints)


@pytest.mark.parametrize("methods", [["get_window", "get_window_state"], ["set_value", "get_window_state"]])
def test_passive_reference_cannot_bind_or_input(methods):
    runtime, checkpoints = fixture(continued=False)
    passive = runtime["tool_calls"][1]
    passive["sky_methods"] = methods
    if "set_value" in methods:
        passive.update(gui_input_count=1, gui_input_number=2)
    with pytest.raises(MODULE.AuditInputError, match="纯 get_window_state"):
        MODULE.audit_stop(runtime, checkpoints)


@pytest.mark.parametrize(("field", "value"), [
    ("call_ordinal", 0), ("output_ordinal", 0), ("call_time", "bad"),
    ("output_time", "2026-10-28T00:00:00Z"), ("top_level_tool", "unknown"),
    ("sky_methods", ["unknown_method"]), ("gui_input_count", 1),
    ("gui_input_number", 2), ("classification", "UNKNOWN"),
    ("sky_methods", []),
])
def test_malformed_catalog_is_rejected(field, value):
    runtime, checkpoints = fixture()
    runtime["tool_calls"][1][field] = value
    with pytest.raises(MODULE.AuditInputError):
        MODULE.audit_stop(runtime, checkpoints)


def test_duplicate_ids_input_and_out_of_order_calls_are_rejected():
    runtime, checkpoints = fixture()
    checkpoints["checkpoints"].append(deepcopy(checkpoints["checkpoints"][0]))
    with pytest.raises(MODULE.AuditInputError, match="checkpoint_id 重复"):
        MODULE.audit_stop(runtime, checkpoints)
    checkpoints["checkpoints"][1]["checkpoint_id"] = "second"
    with pytest.raises(MODULE.AuditInputError, match="重复裁决"):
        MODULE.audit_stop(runtime, checkpoints)
    checkpoints["checkpoints"].pop()
    runtime["tool_calls"][0], runtime["tool_calls"][1] = runtime["tool_calls"][1], runtime["tool_calls"][0]
    with pytest.raises(MODULE.AuditInputError, match="时序"):
        MODULE.audit_stop(runtime, checkpoints)


@pytest.mark.parametrize("target", ["tool_calls", "checkpoints"])
def test_empty_scope_is_never_a_pass(target):
    runtime, checkpoints = fixture()
    (runtime if target == "tool_calls" else checkpoints)[target] = []
    with pytest.raises(MODULE.AuditInputError):
        MODULE.audit_stop(runtime, checkpoints)


def test_failed_input_is_counted_and_discovery_is_explicit():
    runtime, checkpoints = fixture()
    runtime["tool_calls"][0]["classification"] = "TOOL_ACTION_FAILURE"
    assert MODULE.audit_stop(runtime, checkpoints)["scope"]["catalog_input_count"] == 2
    discovery = call(15, methods=[], classification="DISCOVERY_ALLOWED")
    runtime["tool_calls"].append(discovery)
    assert MODULE.audit_stop(runtime, checkpoints)["scope"]["catalog_call_count"] == 4


def write_inputs(tmp_path, *, continued=True):
    runtime, checkpoints = fixture(continued=continued)
    paths = [tmp_path / "runtime.json", tmp_path / "checkpoints.json"]
    for path, value in zip(paths, (runtime, checkpoints)):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return paths


@pytest.mark.parametrize(("continued", "expected"), [(False, 0), (True, 1)])
def test_cli_writes_utf8_report_and_distinguishes_deviation(tmp_path, continued, expected):
    runtime, checkpoints = write_inputs(tmp_path, continued=continued)
    output = tmp_path / "result.json"
    assert MODULE.main(["--runtime-audit", str(runtime), "--checkpoints", str(checkpoints), "--output", str(output)]) == expected
    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    report = json.loads(raw.decode("utf-8"))
    assert len(report["sources"]["runtime_audit"]["sha256"]) == 64
    assert "人工语义" in report["scope"]["limitation"]


def test_cli_refuses_overwrite_including_input_file(tmp_path):
    runtime, checkpoints = write_inputs(tmp_path)
    output = tmp_path / "existing.json"
    output.write_text("原有证据", encoding="utf-8")
    for destination in (output, runtime, checkpoints):
        before = destination.read_bytes()
        assert MODULE.main(["--runtime-audit", str(runtime), "--checkpoints", str(checkpoints), "--output", str(destination)]) == 2
        assert destination.read_bytes() == before


@pytest.mark.parametrize("content", ["{bad", '{"run_id":"a","run_id":"b"}', "not-json-中文"])
def test_cli_parse_error_cannot_write_success(tmp_path, content):
    runtime, checkpoints = write_inputs(tmp_path)
    checkpoints.write_text(content, encoding="utf-8")
    output = tmp_path / "result.json"
    assert MODULE.main(["--runtime-audit", str(runtime), "--checkpoints", str(checkpoints), "--output", str(output)]) == 2
    assert not output.exists()
