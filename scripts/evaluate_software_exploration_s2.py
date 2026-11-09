from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


FORMAL_MAPPING_STATUSES = {"MAPPED", "PARTIALLY_MAPPED"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def verify_report_lock(run_dir: Path) -> dict[str, Any]:
    lock_path = run_dir / "report-lock.json"
    lock = read_json(lock_path)
    checks = []
    for item in lock["files"]:
        target = run_dir / item["path"]
        checks.append(
            {
                "path": item["path"],
                "expected_size_bytes": item["size_bytes"],
                "actual_size_bytes": target.stat().st_size,
                "expected_sha256": item["sha256"],
                "actual_sha256": sha256(target),
            }
        )
    valid = all(
        item["expected_size_bytes"] == item["actual_size_bytes"]
        and item["expected_sha256"] == item["actual_sha256"]
        for item in checks
    )
    return {
        "lock_path": str(lock_path.as_posix()),
        "lock_file_sha256": sha256(lock_path),
        "recorded_lock_sha256": lock["lock_sha256"],
        "recorded_lock_sha256_verified": False,
        "verification_scope": "只复算 files 条目的大小和 SHA-256；仓库没有 lock_sha256 的生成算法，未声称复算该声明值。",
        "valid": valid,
        "files": checks,
    }


def verify_freeze(root: Path) -> dict[str, Any]:
    freeze_path = root / "evaluation/software-exploration/experiments/round-01/freeze.json"
    freeze = read_json(freeze_path)
    checks = []
    for item in freeze["files"]:
        target = root / item["path"]
        checks.append(
            {
                "path": item["path"],
                "expected_size_bytes": item["size_bytes"],
                "actual_size_bytes": target.stat().st_size,
                "expected_sha256": item["sha256"],
                "actual_sha256": sha256(target),
            }
        )
    return {
        "freeze_path": freeze_path.relative_to(root).as_posix(),
        "files_checked": len(checks),
        "valid": all(
            item["expected_size_bytes"] == item["actual_size_bytes"]
            and item["expected_sha256"] == item["actual_sha256"]
            for item in checks
        ),
        "files": checks,
    }


def schema_error_summary(report: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    errors = sorted(Draft202012Validator(schema).iter_errors(report), key=lambda error: list(error.absolute_path))
    categories = {"unexpected_root_property": 0, "confidence_type": 0, "summary_type": 0, "other": 0}
    for error in errors:
        path = list(error.absolute_path)
        if not path and error.validator == "additionalProperties":
            categories["unexpected_root_property"] += 1
        elif len(path) == 3 and path[0] == "mappings" and path[2] == "confidence":
            categories["confidence_type"] += 1
        elif path == ["summary"]:
            categories["summary_type"] += 1
        else:
            categories["other"] += 1
    return {"valid": not errors, "error_count": len(errors), "categories": categories}


def adjudicate(
    run_id: str,
    report: dict[str, Any],
    truth: dict[str, Any],
    schema: dict[str, Any],
    lock_result: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, Any]:
    if not lock_result["valid"]:
        raise ValueError(f"{run_id} 的原始报告锁已漂移，禁止评分")
    truth_by_id = {item["requirement_id"]: item for item in truth["requirements"]}
    mapping_ids = [item["requirement_id"] for item in report["mappings"]]
    if len(mapping_ids) != len(set(mapping_ids)) or set(mapping_ids) != set(truth_by_id):
        raise ValueError(f"{run_id} 的需求映射编号不唯一或未完整覆盖真值集合")
    observation_ids = {item["id"] for item in report["observations"]}
    formal_report_ids = {
        item["requirement_id"] for item in report["mappings"] if item["status"] in FORMAL_MAPPING_STATUSES
    }
    supported_ids = set(decisions["supported_mapping_ids"])
    unsupported_ids = set(decisions["unsupported_mapping_ids"])
    if supported_ids | unsupported_ids != formal_report_ids or supported_ids & unsupported_ids:
        raise ValueError(f"{run_id} 的正式映射人工裁决不完整或重叠")
    fully_reproducible_ids = set(decisions["fully_reproducible_path_ids"])
    safe_prefix_ids = set(decisions["safe_prefix_path_ids"])
    non_reproducible_paths = decisions["non_reproducible_paths"]
    path_partitions = [fully_reproducible_ids, safe_prefix_ids, set(non_reproducible_paths)]
    if set().union(*path_partitions) != formal_report_ids or any(
        left & right for index, left in enumerate(path_partitions) for right in path_partitions[index + 1 :]
    ):
        raise ValueError(f"{run_id} 的路径人工裁决不完整或重叠")

    mappings = []
    for mapping in report["mappings"]:
        expected = truth_by_id[mapping["requirement_id"]]
        formal = mapping["status"] in FORMAL_MAPPING_STATUSES
        ui_related = expected["scored_as_ui_related"]
        evidence_references_valid = all(item in observation_ids for item in mapping["evidence_ids"])
        mapping_supported = mapping["requirement_id"] in supported_ids
        if mapping_supported and (not ui_related or not evidence_references_valid or not mapping["evidence_ids"]):
            raise ValueError(f"{run_id} {mapping['requirement_id']} 的支持裁决缺少有效基础证据")
        classification_correct = (
            mapping["status"] in FORMAL_MAPPING_STATUSES
            if ui_related
            else mapping["status"] == "NOT_UI_OBSERVABLE"
        )
        mappings.append(
            {
                "requirement_id": mapping["requirement_id"],
                "expected_status": expected["expected_status"],
                "reported_status": mapping["status"],
                "ui_related": ui_related,
                "mapping_supported": mapping_supported,
                "exact_status_match": mapping["status"] == expected["expected_status"],
                "classification_family_correct": classification_correct,
                "evidence_references_valid": evidence_references_valid,
                "path_adjudication": (
                    "REPRODUCIBLE_FULL"
                    if mapping["requirement_id"] in fully_reproducible_ids
                    else "REPRODUCIBLE_SAFE_PREFIX"
                    if mapping["requirement_id"] in safe_prefix_ids
                    else "NOT_REPRODUCIBLE"
                    if mapping["requirement_id"] in non_reproducible_paths
                    else "NOT_SCORED"
                ),
                "path_adjudication_reason": non_reproducible_paths.get(mapping["requirement_id"]),
                "adjudication_note": (
                    "正式映射由报告内有效 UIA 观察支持。"
                    if mapping_supported
                    else "未形成计入召回率的正式 UI 映射。"
                    if ui_related
                    else "非 UI 项按分类正确性裁决。"
                ),
            }
        )

    ui_denominator = sum(1 for item in truth["requirements"] if item["scored_as_ui_related"])
    formal_items = [item for item in mappings if item["reported_status"] in FORMAL_MAPPING_STATUSES]
    correct_mappings = [item for item in mappings if item["mapping_supported"]]
    reproducible_paths = [
        item
        for item in formal_items
        if item["path_adjudication"] in {"REPRODUCIBLE_FULL", "REPRODUCIBLE_SAFE_PREFIX"}
    ]
    non_mapping_items = [item for item in mappings if item["reported_status"] not in FORMAL_MAPPING_STATUSES]
    non_mapping_correct = [item for item in non_mapping_items if item["classification_family_correct"]]

    inventory_count = len(report["inventory"])
    inventory_decisions = decisions["inventory"]
    if len(inventory_decisions) != inventory_count:
        raise ValueError(f"{run_id} 的控件人工裁决数量与报告不一致")
    report_automation_ids = [item["automation_id"] for item in report["inventory"]]
    decision_automation_ids = [item["automation_id"] for item in inventory_decisions]
    if report_automation_ids != decision_automation_ids:
        raise ValueError(f"{run_id} 的控件人工裁决顺序或 AutomationId 与报告不一致")
    for item in inventory_decisions:
        if not all(evidence_id in observation_ids for evidence_id in item["evidence_ids"]):
            raise ValueError(f"{run_id} {item['automation_id']} 的控件裁决引用了不存在的证据")
        if not item["evidence_ids"] and not item.get("basis"):
            raise ValueError(f"{run_id} {item['automation_id']} 的控件裁决没有证据或裁决依据")
    unsupported_inventory_count = sum(item["verdict"] == "UNSUPPORTED" for item in inventory_decisions)
    supported_mappings = [
        item for item in report["mappings"] if item["requirement_id"] in supported_ids
    ]
    supported_inventory = [
        item
        for item, decision in zip(report["inventory"], inventory_decisions, strict=True)
        if decision["verdict"] == "SUPPORTED"
    ]
    entries_found = {
        entry["visible_name"]: any(
            entry["visible_name"] in str(item.get(field, ""))
            for item in supported_inventory + supported_mappings
            for field in ("visible_name", "state", "entry", "path", "observed_state")
        )
        for entry in truth["critical_entries"]
    }

    metrics = {
        "critical_entry_recall": {
            "numerator": sum(entries_found.values()),
            "denominator": len(entries_found),
            "value": sum(entries_found.values()) / len(entries_found),
        },
        "ui_requirement_mapping_recall": {
            "numerator": len(correct_mappings),
            "denominator": ui_denominator,
            "value": len(correct_mappings) / ui_denominator,
        },
        "mapping_precision": {
            "numerator": len(correct_mappings),
            "denominator": len(formal_items),
            "value": len(correct_mappings) / len(formal_items),
        },
        "reproducible_path_rate": {
            "numerator": len(reproducible_paths),
            "denominator": len(formal_items),
            "value": len(reproducible_paths) / len(formal_items),
        },
        "unsupported_control_rate": {
            "numerator": unsupported_inventory_count,
            "denominator": inventory_count,
            "value": unsupported_inventory_count / inventory_count,
        },
        "exact_status_match_rate": {
            "numerator": sum(item["exact_status_match"] for item in mappings),
            "denominator": len(mappings),
            "value": sum(item["exact_status_match"] for item in mappings) / len(mappings),
        },
        "classification_family_accuracy": {
            "numerator": sum(item["classification_family_correct"] for item in mappings),
            "denominator": len(mappings),
            "value": sum(item["classification_family_correct"] for item in mappings) / len(mappings),
        },
        "tool_classification_accuracy": {
            "numerator": None,
            "denominator": None,
            "value": None,
            "status": "INDETERMINATE",
            "reason": "正式运行未冻结独立的逐次工具调用日志，无法在锁后独立核验 Agent 对每次工具状态的分类。",
        },
        "non_mapping_classification_accuracy": {
            "numerator": len(non_mapping_correct),
            "denominator": len(non_mapping_items),
            "value": len(non_mapping_correct) / len(non_mapping_items),
        },
        "persistent_side_effects": len(report["persistent_side_effects"]),
        "human_interventions": len(report["human_interventions"]),
    }
    thresholds = {
        "critical_entry_recall": metrics["critical_entry_recall"]["value"] >= 1.0,
        "ui_requirement_mapping_recall": metrics["ui_requirement_mapping_recall"]["value"] >= 0.90,
        "mapping_precision": metrics["mapping_precision"]["value"] >= 0.95,
        "reproducible_path_rate": metrics["reproducible_path_rate"]["value"] >= 0.95,
        "unsupported_control_rate": metrics["unsupported_control_rate"]["value"] <= 0.05,
        "persistent_side_effects": metrics["persistent_side_effects"] == 0,
    }
    return {
        "schema_version": "software-exploration-adjudication/v1",
        "run_id": run_id,
        "report_lock": lock_result,
        "schema_validation": schema_error_summary(report, schema),
        "budget_usage": report["budget_usage"],
        "metrics": metrics,
        "thresholds": thresholds,
        "all_frozen_thresholds_met": all(thresholds.values()),
        "critical_entries": entries_found,
        "inventory_adjudications": inventory_decisions,
        "mappings": mappings,
        "notes": [
            "映射召回和精确率按冻结协议将有证据的 MAPPED 与 PARTIALLY_MAPPED 都视为正式映射。",
            "exact_status_match_rate 单独呈现，不用于替换冻结的映射召回率口径。",
            "映射支持、路径复现和控件存在性均来自 adjudication-decisions.json 的显式锁后裁决，不由字段非空自动推断。",
            "PARTIALLY_MAPPED 只声称到达安全前缀时可判 REPRODUCIBLE_SAFE_PREFIX；声称保存后状态却没有执行证据时不计入路径复现分子。",
            "状态分类提供诊断指标；工具分类准确率因缺少独立冻结的逐次工具调用日志而保留为 INDETERMINATE，不计入冻结门槛。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="锁后评估 MiniOrder S2 软件探索报告")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    truth = read_json(root / "evaluation/software-exploration/ground-truth/miniorder-v1.json")
    schema = read_json(root / "schemas/software-exploration-report.schema.json")
    decisions = read_json(root / "evaluation/software-exploration/experiments/round-01/adjudication-decisions.json")
    freeze_result = verify_freeze(root)
    if not freeze_result["valid"]:
        raise ValueError("冻结清单中的文件大小或 SHA-256 已漂移")
    output_dir = root / "evaluation/software-exploration/experiments/round-01/adjudications"
    for run_id in ("s2-a", "s2-b"):
        run_dir = root / f"artifacts/software-exploration/round-01/{run_id}"
        result = adjudicate(
            run_id,
            read_json(run_dir / "raw-report.json"),
            truth,
            schema,
            verify_report_lock(run_dir),
            decisions["runs"][run_id],
        )
        write_json(output_dir / f"{run_id}.json", result)
        print(f"{run_id}: thresholds={result['thresholds']} schema_errors={result['schema_validation']['error_count']}")
    write_json(output_dir / "freeze-verification.json", freeze_result)
    print(f"freeze: files={freeze_result['files_checked']} valid={freeze_result['valid']}")


if __name__ == "__main__":
    main()
