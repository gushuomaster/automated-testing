"""S1 阶段边界；候选、基线、核验、评分相互独立。"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from testing_platform.domain.documents import StrictModel
from testing_platform.domain.requirements import AnalysisIssue, ParsedRequirements, RequirementItem, SourceReference


class RequirementCandidateItem(StrictModel):
    id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    categories: list[Literal["functional", "performance", "interface", "boundary", "security", "constraint", "exception"]] = Field(min_length=1)
    description: str = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    expected_behavior: str = Field(min_length=1)
    information_nature: Literal["explicit", "derived"] = "explicit"
    rationale: str = ""
    confidence: float = Field(ge=0, le=1)
    source_evidence: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_derived(self):
        if self.information_nature == "derived" and not self.rationale.strip():
            raise ValueError("推导候选必须说明依据")
        return self


class RequirementCandidate(StrictModel):
    schema_version: Literal["requirement-candidate/v1"]
    requirements: list[RequirementCandidateItem]
    ambiguities: list[AnalysisIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self):
        identifiers = [item.id for item in self.requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("候选需求编号不能重复")
        return self


class RequirementBaseline(StrictModel):
    schema_version: Literal["requirement-baseline/v1"]
    parsed: ParsedRequirements

    @model_validator(mode="after")
    def require_v2(self):
        if self.parsed.schema_version != "2.0":
            raise ValueError("S1 基线必须使用 ParsedRequirements v2")
        return self


class VerificationFinding(StrictModel):
    requirement_id: str
    status: Literal["supported", "partially_supported", "unsupported", "indeterminate"]
    code: str
    message: str
    segment_ids: list[str] = Field(default_factory=list)


class VerificationResult(StrictModel):
    schema_version: Literal["verification-result/v1"]
    baseline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["deterministic", "semantic"]
    findings: list[VerificationFinding]


class ReconciliationMerge(StrictModel):
    requirement_ids: list[str] = Field(min_length=2)
    retained_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_members(self):
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("跨块合并成员不能重复")
        if self.retained_id not in self.requirement_ids:
            raise ValueError("保留编号必须属于跨块合并成员")
        return self


class ReconciliationRelation(StrictModel):
    requirement_ids: list[str] = Field(min_length=2)
    description: str = Field(min_length=1)
    impact: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_members(self):
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("跨块关系成员不能重复")
        return self


class RequirementReconciliation(StrictModel):
    schema_version: Literal["requirement-reconciliation/v1"]
    merges: list[ReconciliationMerge] = Field(default_factory=list)
    conflicts: list[ReconciliationRelation] = Field(default_factory=list)
    ambiguities: list[ReconciliationRelation] = Field(default_factory=list)


class Metric(StrictModel):
    numerator: float = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None


class EvaluationResult(StrictModel):
    schema_version: Literal["evaluation-result/v1"]
    role: Literal["calibration", "development", "regression", "formal"]
    report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    metrics: dict[str, Metric]
    critical_errors: list[str]
    unresolved: list[str]
    passed: bool | None
