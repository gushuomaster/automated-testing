"""只读核对人工停止裁决与规范化调用目录；不解释 GUI 或执行工具。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


INPUT_METHODS = frozenset({"click", "set_value", "press_key", "activate_window"})
READ_METHODS = frozenset({"list_apps", "get_window", "get_window_state"})
CLASSIFICATIONS = frozenset({
    "DISCOVERY_ALLOWED", "TOOL_ACTION_FAILURE", "TOOL_CALL_SUCCESS",
    "TOOL_CALL_SUCCESS__FOCUS_METADATA_UNRELIABLE",
    "TOOL_CALL_SUCCESS__IMMEDIATE_READBACK_LAG_CONFIRMED_BY_LATER_PASSIVE_READ",
    "TOOL_CALL_SUCCESS__INTENDED_BUTTON_OUTCOME_UNCONFIRMED",
})
OUTCOMES = frozenset({"CONFIRMED", "UNRESOLVED", "FOCUS_METADATA_ONLY"})
PASSIVE_FIELDS = ("passive_call_ordinal", "passive_output_ordinal", "passive_outcome")


class AuditInputError(ValueError):
    """输入缺失或不一致，不能作出停止审计结论。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditInputError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} 必须是对象")
    return value


def _text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} 必须是非空文本")
    return value


def _ordinal(value: Any, label: str) -> int:
    _require(type(value) is int and value >= 0, f"{label} 必须是非负整数 ordinal")
    return value


def _time(value: Any, label: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditInputError(f"{label} 时间无效") from exc
    _require(stamp.tzinfo is not None, f"{label} 必须包含时区")
    return stamp


def _validate_calls(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    calls = runtime.get("tool_calls")
    _require(isinstance(calls, list) and bool(calls), "tool_calls 不能为空")
    seen_ordinals: set[int] = set()
    seen_observations: set[str] = set()
    previous_output = -1
    previous_time: datetime | None = None
    input_number = 0
    for index, raw in enumerate(calls):
        call = _object(raw, f"tool_calls[{index}]")
        start = _ordinal(call.get("call_ordinal"), "call_ordinal")
        end = _ordinal(call.get("output_ordinal"), "output_ordinal")
        _require(start not in seen_ordinals and end not in seen_ordinals, "调用/输出 ordinal 重复")
        _require(previous_output < start < end, "调用目录必须按调用/输出 ordinal 严格时序排列且不重叠")
        seen_ordinals.update((start, end))
        begin_time = _time(call.get("call_time"), "call_time")
        end_time = _time(call.get("output_time"), "output_time")
        _require(begin_time <= end_time and (previous_time is None or previous_time <= begin_time),
                 "调用/输出时间与目录时序不一致")
        _require(call.get("top_level_tool") == "exec", "仅支持已人工核验的 exec 调用目录")
        methods = call.get("sky_methods")
        _require(isinstance(methods, list) and all(isinstance(item, str) for item in methods),
                 "sky_methods 必须是方法名数组")
        _require(all(item in INPUT_METHODS | READ_METHODS for item in methods),
                 "未知 Sky 方法，必须先明确分类，不能静默忽略")
        classification = call.get("classification")
        _require(isinstance(classification, str) and classification in CLASSIFICATIONS,
                 "未知或缺失的工具分类")
        _require(bool(methods) == (classification != "DISCOVERY_ALLOWED"), "发现工具分类与方法目录不一致")
        count = sum(method in INPUT_METHODS for method in methods)
        _require(count <= 1, "一次目录调用含多个输入，无法定位动作后决策边界")
        _require(type(call.get("gui_input_count")) is int and call["gui_input_count"] == count,
                 "gui_input_count 与显式方法分类不一致")
        if count:
            input_number += 1
            _require(type(call.get("gui_input_number")) is int and call["gui_input_number"] == input_number,
                     "gui_input_number 必须连续唯一，失败输入也计数")
        else:
            _require(call.get("gui_input_number") is None, "无输入调用不能有 gui_input_number")
        observation = call.get("observation_id")
        if observation is not None:
            _text(observation, "observation_id")
            _require(observation not in seen_observations, "observation_id 重复")
            seen_observations.add(observation)
        previous_output, previous_time = end, end_time
    return calls


def audit_stop(runtime: Any, checkpoints: Any) -> dict[str, Any]:
    """检查点语义来自人工；仅验证结构和所提供目录中的后续输入。"""
    runtime = _object(runtime, "runtime-audit")
    checkpoints = _object(checkpoints, "checkpoints")
    run_id = _text(runtime.get("run_id"), "runtime-audit.run_id")
    _require(checkpoints.get("schema_version") == "exploration-stop-checkpoints/v1", "检查点 schema_version 不支持")
    _require(checkpoints.get("run_id") == run_id, "两个输入的 run_id 不一致")
    reviewer = _text(checkpoints.get("reviewer"), "reviewer")
    scope_note = _text(checkpoints.get("scope_note"), "scope_note")
    calls = _validate_calls(runtime)
    by_call = {call["call_ordinal"]: call for call in calls}
    inputs = [call["call_ordinal"] for call in calls if call["gui_input_count"]]
    rows = checkpoints.get("checkpoints")
    _require(isinstance(rows, list) and bool(rows), "checkpoints 审核范围不能为空")
    ids: set[str] = set()
    reviewed_inputs: set[int] = set()
    results: list[dict[str, Any]] = []
    stops: list[dict[str, Any]] = []
    for raw in rows:
        row = _object(raw, "checkpoint")
        checkpoint_id = _text(row.get("checkpoint_id"), "checkpoint_id")
        _require(checkpoint_id not in ids, "checkpoint_id 重复")
        ids.add(checkpoint_id)
        reason = _text(row.get("reason"), "reason（人工语义依据）")
        start = _ordinal(row.get("input_call_ordinal"), "input_call_ordinal")
        immediate = _ordinal(row.get("immediate_output_ordinal"), "immediate_output_ordinal")
        _require(start in by_call and start in inputs, "input_call_ordinal 必须引用真实输入调用")
        _require(start not in reviewed_inputs, "同一输入被重复裁决")
        reviewed_inputs.add(start)
        _require(by_call[start]["output_ordinal"] == immediate, "即时输出不属于所引用输入调用")
        outcome = row.get("immediate_outcome")
        _require(isinstance(outcome, str) and outcome in OUTCOMES, "缺少或非法的 immediate_outcome，不能从工具成功推断")
        has_passive = any(row.get(key) is not None for key in PASSIVE_FIELDS)
        _require(outcome != "UNRESOLVED" or has_passive, "UNRESOLVED 必须引用一次纯被动复核及其人工结论")
        pending: list[int] = []
        continued: list[int] = []
        cutoff = None
        passive_start = passive_end = passive_outcome = None
        if has_passive:
            passive_start = _ordinal(row.get("passive_call_ordinal"), "passive_call_ordinal")
            passive_end = _ordinal(row.get("passive_output_ordinal"), "passive_output_ordinal")
            passive_outcome = row.get("passive_outcome")
            _require(isinstance(passive_outcome, str) and passive_outcome in {"CONFIRMED", "UNRESOLVED"},
                     "缺少或非法的 passive_outcome")
            _require(passive_start in by_call, "被动复核调用不存在")
            passive = by_call[passive_start]
            _require(passive["output_ordinal"] == passive_end, "被动输出不属于所引用复核调用")
            _require(immediate < passive_start < passive_end, "被动复核必须在即时输出之后")
            _require(passive["sky_methods"] == ["get_window_state"] and passive["gui_input_count"] == 0,
                     "被动复核必须是一次纯 get_window_state，不得含绑定或输入")
            _require(outcome == "UNRESOLVED" or passive_outcome == "CONFIRMED",
                     "非未决分支不能附加新的 UNRESOLVED 语义；请提供独立明确检查点")
            if outcome == "UNRESOLVED":
                pending = [ordinal for ordinal in inputs if immediate < ordinal < passive_end]
                if passive_outcome == "UNRESOLVED":
                    cutoff = passive_end
                    continued = [ordinal for ordinal in inputs if ordinal > cutoff]
                    stops.append({"checkpoint_id": checkpoint_id, "after_output_ordinal": cutoff,
                                  "first_continued_input_call_ordinal": continued[0] if continued else None})
        violations = sorted(set(pending + continued))
        if violations:
            verdict = "STOP_RULE_DEVIATION"
        elif cutoff is not None:
            verdict = "STOP_OBSERVED_IN_PROVIDED_CATALOG"
        elif outcome == "FOCUS_METADATA_ONLY":
            verdict = "FOCUS_METADATA_EXCEPTION"
        else:
            verdict = "CONFIRMED_CONTINUATION_ALLOWED"
        results.append({"checkpoint_id": checkpoint_id, "input_call_ordinal": start,
                        "immediate_output_ordinal": immediate, "immediate_outcome": outcome,
                        "passive_call_ordinal": passive_start, "passive_output_ordinal": passive_end,
                        "passive_outcome": passive_outcome, "reason": reason, "verdict": verdict,
                        "stop_after_output_ordinal": cutoff,
                        "before_passive_input_call_ordinals": pending,
                        "after_stop_input_call_ordinals": continued,
                        "continued_input_call_ordinals": violations})
    deviations = [result for result in results if result["continued_input_call_ordinals"]]
    return {
        "schema_version": "exploration-stop-audit/v1", "run_id": run_id,
        "status": "REVIEWED_CHECKPOINT_DEVIATIONS" if deviations else "NO_DEVIATION_IN_REVIEWED_CHECKPOINTS",
        "deviation_checkpoint_count": len(deviations),
        "first_stop": min(stops, key=lambda stop: stop["after_output_ordinal"]) if stops else None,
        "first_violation_input_call_ordinal": min(
            (ordinal for result in results for ordinal in result["continued_input_call_ordinals"]), default=None),
        "scope": {"reviewer": reviewer, "scope_note": scope_note,
                  "reviewed_checkpoint_ids": [result["checkpoint_id"] for result in results],
                  "catalog_call_count": len(calls), "catalog_input_count": len(inputs),
                  "catalog_first_call_ordinal": calls[0]["call_ordinal"],
                  "catalog_last_output_ordinal": calls[-1]["output_ordinal"],
                  "limitation": "仅核对所审检查点与提供目录；人工语义正确性、目录完整性及原始日志一致性须外部核验。无偏离不等于全日志、全协议或可靠停止通过。"},
        "checkpoints": results,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"JSON 字段重复：{key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-audit", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        sources = {}
        documents = []
        for name, path in (("runtime_audit", args.runtime_audit), ("checkpoints", args.checkpoints)):
            data = path.read_bytes()
            documents.append(json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object))
            sources[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest()}
        report = audit_stop(*documents)
        report["sources"] = sources
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        print(f"停止审计失败，未得出通过结论：{exc}", file=sys.stderr)
        return 2
    print(f"{report['status']}：{args.output}")
    return 1 if report["deviation_checkpoint_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
