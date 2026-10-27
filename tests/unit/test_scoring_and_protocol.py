from __future__ import annotations

from pathlib import Path

import pytest

from testing_platform.domain.requirements import ParsedRequirements
from testing_platform.evaluation.protocol import (
    Budget, BudgetUsage, FrozenProtocol, audit_agent_input, budget_violations, lock_files, verify_lock,
)
from testing_platform.evaluation.scoring import (
    GroundTruthSet, ReviewDecision, adjudicate, score,
)


def truth():
    return GroundTruthSet.model_validate({
        "schema_version": "ground-truth/v1", "material_sha256": "a" * 64,
        "matching_rules_version": "v1", "reviewer_ids": ["reviewer-a", "reviewer-b"],
        "requirements": [
            {"id": "T-F", "category": "functional", "statement": "保存订单", "source_segment_ids": ["s1"], "atomicity_basis": "一个保存行为"},
            {"id": "T-P", "category": "performance", "statement": "2 秒内", "source_segment_ids": ["s2"], "atomicity_basis": "一个时限", "critical_tokens": ["2 秒"]},
            {"id": "T-I", "category": "interface", "statement": "JSON 接口", "source_segment_ids": ["s3"], "atomicity_basis": "一个接口契约"},
        ]})


def output():
    requirements = []
    for identifier, category, segment, description in (
        ("R-F", "functional", "s1", "保存订单"),
        ("R-P", "performance", "s2", "2 秒内"),
        ("R-I", "interface", "s3", "JSON 接口"),
    ):
        requirements.append({"id": identifier, "target": identifier, "categories": [category],
                             "description": description, "expected_behavior": description, "confidence": 1,
                             "source_evidence": [{"path": "formal.md", "sha256": "a" * 64,
                                                  "segment_id": segment,
                                                  "locator": {"format": "markdown", "line_start": 1, "line_end": 1}}]})
    return ParsedRequirements.model_validate({"schema_version": "2.0", "source": {"path": "formal.md", "sha256": "a" * 64},
                                              "requirements": requirements,
                                              "trace_index": {r["id"]: [r["source_evidence"][0]["segment_id"]] for r in requirements}})


def decisions(status="complete", critical_errors=None):
    items = []
    for reviewer in ("reviewer-a", "reviewer-b"):
        for output_id, truth_id in (("R-F", "T-F"), ("R-P", "T-P"), ("R-I", "T-I")):
            items.append(ReviewDecision(reviewer_id=reviewer, output_id=output_id, truth_id=truth_id,
                                        status=status, source_locator_valid=True,
                                        critical_errors=critical_errors or [], rationale="逐条来源一致"))
    return items


def test_independent_review_reproducibly_adjudicates_and_scores_all_denominators():
    adjudication = adjudicate(decisions())
    scored = score(truth(), output(), adjudication, role="formal", report_sha256="c" * 64)
    assert not adjudication.unresolved and scored.result.passed is True
    for name in ("functional_precision", "functional_recall", "performance_precision", "performance_recall",
                 "interface_precision", "interface_recall", "source_locator_validity"):
        assert scored.result.metrics[name].value == 1
    assert scored.result.metrics["unsupported_output_ratio"].value == 0


def test_partial_dispute_and_critical_error_remain_auditable():
    partial = score(truth(), output(), adjudicate(decisions("partial")), role="formal", report_sha256="c" * 64)
    assert partial.result.metrics["precision"].numerator == 1.5
    assert partial.result.metrics["recall"].numerator == 1.5
    assert partial.result.passed is False
    disagreement = decisions()
    disagreement[-1] = disagreement[-1].model_copy(update={"status": "no_match", "truth_id": None})
    adjudication = adjudicate(disagreement)
    assert adjudication.unresolved == ["R-I"] and next(item for item in adjudication.matches if item.output_id == "R-I").status == "disputed"
    critical = score(truth(), output(), adjudicate(decisions(critical_errors=["2 秒被改写为 3 秒"])),
                     role="formal", report_sha256="c" * 64)
    assert critical.result.critical_errors and critical.result.passed is False


def test_scoring_rejects_duplicate_positive_match_wrong_category_and_material_drift():
    duplicated = decisions()
    for reviewer in ("reviewer-a", "reviewer-b"):
        duplicated.append(ReviewDecision(reviewer_id=reviewer, output_id="R-X", truth_id="T-F",
                                         status="complete", source_locator_valid=True, rationale="重复"))
    extra = output().model_copy(deep=True)
    copied = extra.requirements[0].model_copy(update={"id": "R-X"})
    extra.requirements.append(copied)
    extra.trace_index["R-X"] = ["s1"]
    with pytest.raises(ValueError, match="多个正向匹配"):
        score(truth(), extra, adjudicate(duplicated), role="formal", report_sha256="c" * 64)

    with pytest.raises(ValueError, match="必须引用真值需求"):
        ReviewDecision(reviewer_id="reviewer-a", output_id="R-X", status="duplicate",
                       source_locator_valid=True, rationale="缺少被重复的真值")

    orphan_duplicate = decisions()
    for reviewer in ("reviewer-a", "reviewer-b"):
        orphan_duplicate.append(ReviewDecision(reviewer_id=reviewer, output_id="R-X", truth_id="T-F",
                                                status="duplicate", source_locator_valid=True,
                                                rationale="没有对应正向匹配"))
    only_interface = output().model_copy(deep=True)
    only_interface.requirements = [item for item in only_interface.requirements if item.id != "R-F"]
    only_interface.trace_index.pop("R-F")
    duplicate_output = output().requirements[0].model_copy(update={"id": "R-X"})
    only_interface.requirements.append(duplicate_output)
    only_interface.trace_index["R-X"] = ["s1"]
    with pytest.raises(ValueError, match="已有正向匹配"):
        score(truth(), only_interface, adjudicate([
            item for item in orphan_duplicate if item.output_id != "R-F"
        ]), role="formal", report_sha256="c" * 64)

    mismatched = output().model_copy(deep=True)
    mismatched.requirements[0].categories = ["performance"]
    scored = score(truth(), mismatched, adjudicate(decisions()), role="formal", report_sha256="c" * 64)
    assert scored.result.metrics["performance_precision"].value < 1

    drifted = output().model_copy(deep=True)
    drifted.source.sha256 = "f" * 64
    for requirement in drifted.requirements:
        requirement.source_evidence[0].sha256 = "f" * 64
    with pytest.raises(ValueError, match="材料哈希"):
        score(truth(), drifted, adjudicate(decisions()), role="formal", report_sha256="c" * 64)


def test_adjudication_requires_distinct_reviewers_and_frozen_credit():
    with pytest.raises(ValueError, match="两名独立复核者"):
        adjudicate([decisions()[0]])
    duplicate_vote = [decisions()[0], decisions()[0]]
    with pytest.raises(ValueError, match="重复投票"):
        adjudicate(duplicate_vote)
    partial_truth = truth().model_copy(update={"partial_credit": 0.25})
    partial = adjudicate(decisions("partial"), partial_credit=0.25)
    assert score(partial_truth, output(), partial, role="formal", report_sha256="c" * 64).result.metrics["precision"].numerator == 0.75


def protocol():
    return FrozenProtocol(schema_version="formal-protocol/v1", material_id="formal-1", material_sha256="a" * 64,
                          truth_sha256="b" * 64, matching_rules_sha256="c" * 64, model_id="fixed-model",
                          skill_version="1.0.0", prompt_hashes={"extractor": "d" * 64},
                          budget=Budget(max_agent_calls=10, max_input_tokens=50000, max_output_tokens=10000),
                          allowed_inputs=["formal.md", "SKILL.md", "schemas"],
                          forbidden_path_fragments=["ground-truth", "历史答案.xlsx", "/src/"])


def test_isolation_audit_and_report_lock_detect_mutation(tmp_path):
    allowed = {"document": "formal.md", "segments": [{"text": "公开需求"}], "skill": "SKILL.md"}
    assert audit_agent_input(allowed, protocol()).passed
    blocked = {"ground_truth": {"answer": 1}, "path": "evaluation/ground-truth/formal.json", "source": "/src/product.py"}
    report = audit_agent_input(blocked, protocol())
    assert not report.passed and {item.code for item in report.findings} == {"FORBIDDEN_KEY", "FORBIDDEN_PATH"}
    first, second = tmp_path / "report.json", tmp_path / "evidence.json"
    first.write_text("{}", encoding="utf-8"); second.write_text("[]", encoding="utf-8")
    lock = lock_files([first, second], tmp_path)
    assert verify_lock(lock, tmp_path) == []
    first.write_text('{"changed":true}', encoding="utf-8")
    assert verify_lock(lock, tmp_path) == ["report.json"]
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="超出根目录"):
        lock_files([outside], tmp_path)
    usage = BudgetUsage(agent_calls=11, input_tokens=1, output_tokens=1, revisions=0)
    assert budget_violations(protocol().budget, usage) == ["AGENT_CALLS_EXCEEDED"]
