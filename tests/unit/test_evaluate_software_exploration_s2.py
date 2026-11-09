from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evaluate_software_exploration_s2", ROOT / "scripts/evaluate_software_exploration_s2.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _evaluate(run_id: str) -> dict:
    truth = MODULE.read_json(ROOT / "evaluation/software-exploration/ground-truth/miniorder-v1.json")
    schema = MODULE.read_json(ROOT / "schemas/software-exploration-report.schema.json")
    run_dir = ROOT / f"artifacts/software-exploration/round-01/{run_id}"
    decisions = MODULE.read_json(
        ROOT / "evaluation/software-exploration/experiments/round-01/adjudication-decisions.json"
    )
    return MODULE.adjudicate(
        run_id,
        MODULE.read_json(run_dir / "raw-report.json"),
        truth,
        schema,
        MODULE.verify_report_lock(run_dir),
        decisions["runs"][run_id],
    )


def test_locked_reports_are_unchanged() -> None:
    assert MODULE.verify_report_lock(ROOT / "artifacts/software-exploration/round-01/s2-a")["valid"]
    assert MODULE.verify_report_lock(ROOT / "artifacts/software-exploration/round-01/s2-b")["valid"]


def test_adjudication_refuses_a_drifted_report_lock() -> None:
    truth = MODULE.read_json(ROOT / "evaluation/software-exploration/ground-truth/miniorder-v1.json")
    schema = MODULE.read_json(ROOT / "schemas/software-exploration-report.schema.json")
    run_dir = ROOT / "artifacts/software-exploration/round-01/s2-a"
    decisions = MODULE.read_json(
        ROOT / "evaluation/software-exploration/experiments/round-01/adjudication-decisions.json"
    )["runs"]["s2-a"]
    lock_result = MODULE.verify_report_lock(run_dir)
    lock_result["valid"] = False
    with pytest.raises(ValueError, match="报告锁已漂移"):
        MODULE.adjudicate(
            "s2-a",
            MODULE.read_json(run_dir / "raw-report.json"),
            truth,
            schema,
            lock_result,
            decisions,
        )


def test_s2_a_fails_only_frozen_mapping_recall_threshold() -> None:
    result = _evaluate("s2-a")
    assert result["metrics"]["ui_requirement_mapping_recall"]["numerator"] == 36
    assert result["metrics"]["ui_requirement_mapping_recall"]["denominator"] == 46
    assert not result["thresholds"]["ui_requirement_mapping_recall"]
    assert all(value for key, value in result["thresholds"].items() if key != "ui_requirement_mapping_recall")


def test_s2_b_meets_path_threshold_with_explicit_safe_prefix_adjudications() -> None:
    result = _evaluate("s2-b")
    assert result["metrics"]["ui_requirement_mapping_recall"]["numerator"] == 43
    assert result["metrics"]["ui_requirement_mapping_recall"]["denominator"] == 46
    assert result["metrics"]["reproducible_path_rate"]["numerator"] == 41
    assert result["metrics"]["reproducible_path_rate"]["denominator"] == 43
    assert result["thresholds"]["reproducible_path_rate"]
    assert result["all_frozen_thresholds_met"]


def test_freeze_manifest_files_are_unchanged() -> None:
    result = MODULE.verify_freeze(ROOT)
    assert result["files_checked"] == 11
    assert result["valid"]


def test_schema_errors_are_preserved_as_format_adjudication() -> None:
    assert _evaluate("s2-a")["schema_validation"]["error_count"] == 54
    assert _evaluate("s2-b")["schema_validation"]["error_count"] == 53


def test_tool_classification_accuracy_is_not_invented_without_independent_logs() -> None:
    for run_id in ("s2-a", "s2-b"):
        metric = _evaluate(run_id)["metrics"]["tool_classification_accuracy"]
        assert metric["status"] == "INDETERMINATE"
        assert metric["numerator"] is None
        assert metric["denominator"] is None
