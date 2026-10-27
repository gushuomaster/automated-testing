from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import Field, model_validator

from testing_platform.domain.analysis import EvaluationResult, Metric
from testing_platform.domain.documents import StrictModel
from testing_platform.domain.requirements import ParsedRequirements

Category = Literal["functional", "performance", "interface", "boundary", "security", "constraint", "exception"]
MatchStatus = Literal["complete", "partial", "no_match", "duplicate", "disputed"]
CREDIT = {"complete": 1.0, "partial": 0.5, "no_match": 0.0, "duplicate": 0.0, "disputed": 0.0}


class TruthRequirement(StrictModel):
    id: str
    category: Category
    statement: str
    source_segment_ids: list[str] = Field(min_length=1)
    atomicity_basis: str
    critical_tokens: list[str] = Field(default_factory=list)


class GroundTruthSet(StrictModel):
    schema_version: Literal["ground-truth/v1"]
    material_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirements: list[TruthRequirement]
    matching_rules_version: str
    partial_credit: float = Field(default=0.5, ge=0, le=1)
    reviewer_ids: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_ids(self):
        ids = [item.id for item in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("真值需求编号不能重复")
        if len(self.reviewer_ids) != len(set(self.reviewer_ids)):
            raise ValueError("独立复核者编号不能重复")
        return self


class ReviewDecision(StrictModel):
    reviewer_id: str
    output_id: str
    truth_id: str | None = None
    status: MatchStatus
    source_locator_valid: bool = False
    critical_errors: list[str] = Field(default_factory=list)
    rationale: str

    @model_validator(mode="after")
    def validate_match(self):
        if self.status in {"complete", "partial", "duplicate"} and not self.truth_id:
            raise ValueError("有效匹配必须引用真值需求")
        if self.status in {"no_match", "disputed"} and self.truth_id:
            raise ValueError("无匹配或争议决定不能预先绑定真值")
        return self


class AdjudicatedMatch(StrictModel):
    output_id: str
    truth_id: str | None
    status: MatchStatus
    credit: float = Field(ge=0, le=1)
    source_locator_valid: bool
    critical_errors: list[str]
    reviewer_ids: list[str]
    rationale: str

    @model_validator(mode="after")
    def validate_match(self):
        if self.status in {"complete", "partial", "duplicate"} and not self.truth_id:
            raise ValueError("有效匹配或重复项必须引用真值需求")
        if self.status in {"no_match", "disputed"} and self.truth_id:
            raise ValueError("无匹配或争议裁决不能绑定真值需求")
        return self


class AdjudicationResult(StrictModel):
    schema_version: Literal["adjudication/v1"]
    matches: list[AdjudicatedMatch]
    unresolved: list[str]

    @model_validator(mode="after")
    def validate_output_ids(self):
        identifiers = [item.output_id for item in self.matches]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("同一输出只能有一条最终裁决")
        return self


def adjudicate(decisions: list[ReviewDecision], *, required_reviewer_ids: list[str] | None = None,
               partial_credit: float = 0.5) -> AdjudicationResult:
    if not 0 <= partial_credit <= 1:
        raise ValueError("部分正确分值必须在 0 到 1 之间")
    groups = defaultdict(list)
    for item in decisions:
        groups[item.output_id].append(item)
    matches, unresolved = [], []
    for output_id, reviews in sorted(groups.items()):
        reviewers = [item.reviewer_id for item in reviews]
        if len(reviewers) != len(set(reviewers)):
            raise ValueError(f"{output_id}: 同一复核者不能重复投票")
        required = set(required_reviewer_ids or [])
        if (required and set(reviewers) != required) or (not required and len(reviewers) < 2):
            raise ValueError(f"{output_id}: 缺少两名独立复核者的一致决定")
        signatures = {(item.truth_id, item.status, item.source_locator_valid, tuple(sorted(item.critical_errors)))
                      for item in reviews}
        if len(signatures) != 1:
            unresolved.append(output_id)
            matches.append(AdjudicatedMatch(output_id=output_id, truth_id=None, status="disputed", credit=0,
                                             source_locator_valid=False, critical_errors=[],
                                             reviewer_ids=[item.reviewer_id for item in reviews],
                                             rationale="独立复核结论不一致，等待裁决"))
            continue
        truth_id, status, source_valid, errors = next(iter(signatures))
        credit = partial_credit if status == "partial" else CREDIT[status]
        matches.append(AdjudicatedMatch(output_id=output_id, truth_id=truth_id, status=status,
                                         credit=credit, source_locator_valid=source_valid,
                                         critical_errors=list(errors), reviewer_ids=[item.reviewer_id for item in reviews],
                                         rationale=" | ".join(item.rationale for item in reviews)))
    return AdjudicationResult(schema_version="adjudication/v1", matches=matches, unresolved=unresolved)


class ScoredEvaluation(StrictModel):
    result: EvaluationResult
    matches: list[AdjudicatedMatch]
    unmatched_truth_ids: list[str]
    unmatched_output_ids: list[str]
    failed_segments: list[str] = Field(default_factory=list)


def _metric(numerator: float, denominator: int) -> Metric:
    return Metric(numerator=numerator, denominator=denominator,
                  value=numerator / denominator if denominator else None)


def score(truth: GroundTruthSet, output: ParsedRequirements, adjudication: AdjudicationResult,
          *, role: Literal["calibration", "development", "regression", "formal"], report_sha256: str) -> ScoredEvaluation:
    output_ids = {item.id for item in output.requirements}
    material_hashes = {output.source.sha256, *(item.sha256 for item in output.additional_sources)}
    if truth.material_sha256 not in material_hashes:
        raise ValueError("输出需求基线与真值材料哈希不一致")
    truth_by_id = {item.id: item for item in truth.requirements}
    matches_by_output = {item.output_id: item for item in adjudication.matches}
    if not set(matches_by_output) <= output_ids:
        raise ValueError("裁决引用了不存在的输出需求")
    if any(item.truth_id and item.truth_id not in truth_by_id for item in adjudication.matches):
        raise ValueError("裁决引用了不存在的真值需求")
    expected_reviewers = set(truth.reviewer_ids)
    if any(set(item.reviewer_ids) != expected_reviewers for item in adjudication.matches):
        raise ValueError("裁决没有包含冻结的全部独立复核者")
    for item in adjudication.matches:
        expected_credit = truth.partial_credit if item.status == "partial" else CREDIT[item.status]
        if item.credit != expected_credit:
            raise ValueError("裁决分值与冻结匹配状态规则不一致")
        if item.status in {"complete", "partial"} and item.truth_id is None:
            raise ValueError("有效匹配没有引用真值需求")
    positive_by_truth = defaultdict(list)
    for item in adjudication.matches:
        if item.truth_id and item.credit > 0:
            positive_by_truth[item.truth_id].append(item.output_id)
    duplicates = {key: value for key, value in positive_by_truth.items() if len(value) > 1}
    if duplicates:
        raise ValueError(f"同一真值存在多个正向匹配，重复项必须标记 duplicate：{duplicates}")
    for item in adjudication.matches:
        if item.status == "duplicate" and len(positive_by_truth[item.truth_id]) != 1:
            raise ValueError(f"{item.output_id}: duplicate 必须引用恰好一个已有正向匹配的真值")
    precision_credit = sum(matches_by_output.get(identifier, AdjudicatedMatch(
        output_id=identifier, truth_id=None, status="no_match", credit=0, source_locator_valid=False,
        critical_errors=[], reviewer_ids=[], rationale="未裁决")).credit for identifier in output_ids)
    truth_credit = {identifier: 0.0 for identifier in truth_by_id}
    for item in adjudication.matches:
        if item.truth_id:
            truth_credit[item.truth_id] = max(truth_credit[item.truth_id], item.credit)
    metrics = {
        "precision": _metric(precision_credit, len(output_ids)),
        "recall": _metric(sum(truth_credit.values()), len(truth_by_id)),
        "source_locator_validity": _metric(sum(item.source_locator_valid for item in matches_by_output.values()), len(output_ids)),
        "unsupported_output_ratio": _metric(sum(matches_by_output.get(identifier) is None or
                                                  matches_by_output[identifier].status == "no_match"
                                                  for identifier in output_ids), len(output_ids)),
    }
    p, r = metrics["precision"].value, metrics["recall"].value
    f1 = None if p is None or r is None else (2 * p * r / (p + r) if p + r else 0.0)
    metrics["f1"] = Metric(numerator=f1 or 0, denominator=1, value=f1)
    for category in ("functional", "performance", "interface"):
        category_truth = {item.id for item in truth.requirements if item.category == category}
        category_outputs = {item.id for item in output.requirements if category in item.categories}
        category_precision = sum(matches_by_output[item].credit for item in category_outputs
                                 if item in matches_by_output and matches_by_output[item].truth_id in category_truth)
        category_recall = sum(truth_credit[item] for item in category_truth)
        metrics[f"{category}_precision"] = _metric(category_precision, len(category_outputs))
        metrics[f"{category}_recall"] = _metric(category_recall, len(category_truth))
    critical = [error for item in adjudication.matches for error in item.critical_errors]
    unresolved = sorted(set(adjudication.unresolved) | (output_ids - set(matches_by_output))
                        | {item.output_id for item in adjudication.matches if item.status == "disputed"})
    passed = None
    if role == "formal":
        required = [metrics[f"{category}_{kind}"].value for category in ("functional", "performance", "interface")
                    for kind in ("precision", "recall")]
        passed = (all(value is not None and value >= 0.8 for value in required)
                  and metrics["source_locator_validity"].value is not None
                  and metrics["source_locator_validity"].value >= 0.95
                  and metrics["unsupported_output_ratio"].value is not None
                  and metrics["unsupported_output_ratio"].value <= 0.05
                  and not critical and not unresolved)
    result = EvaluationResult(schema_version="evaluation-result/v1", role=role, report_sha256=report_sha256,
                              metrics=metrics, critical_errors=critical, unresolved=unresolved, passed=passed)
    matched_truth = {item.truth_id for item in adjudication.matches if item.truth_id and item.credit > 0}
    unmatched_outputs = {identifier for identifier in output_ids
                         if identifier not in matches_by_output or matches_by_output[identifier].credit == 0}
    return ScoredEvaluation(result=result, matches=adjudication.matches,
                            unmatched_truth_ids=sorted(set(truth_by_id) - matched_truth),
                            unmatched_output_ids=sorted(unmatched_outputs), failed_segments=output.failed_segments)
