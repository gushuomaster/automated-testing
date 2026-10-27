from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from testing_platform.domain.documents import SourceLocator


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = ""
    name: str = ""
    media_type: str = ""


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = ""
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    excerpt: str | None = None
    segment_id: str | None = None
    locator: SourceLocator | None = None


class UnresolvedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    reason: str
    requirement_id: str | None = None


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = ""
    description: str = ""
    requirement_type: str = ""
    priority: str = ""
    risk: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    source_evidence: list[SourceReference] = Field(default_factory=list)
    target: str = ""
    categories: list[Literal["functional", "performance", "interface", "boundary", "security", "constraint", "exception"]] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expected_behavior: str = ""
    information_nature: Literal["explicit", "derived", "historical", "assumption"] = "explicit"
    rationale: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: Literal["supported", "partially_supported", "unsupported", "indeterminate"] | None = None


class AnalysisIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    impact: str
    requirement_ids: list[str] = Field(default_factory=list)
    source_evidence: list[SourceReference] = Field(default_factory=list)


class TestTypeRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_ids: list[str] = Field(min_length=1)
    test_type: str
    rationale: str
    confidence: float = Field(ge=0, le=1)


class ParsedRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "2.0"] = "1.0"
    source: SourceDocument
    requirements: list[RequirementItem]
    unresolved_fields: list[UnresolvedField] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    additional_sources: list[SourceDocument] = Field(default_factory=list)
    ambiguities: list[AnalysisIssue] = Field(default_factory=list)
    conflicts: list[AnalysisIssue] = Field(default_factory=list)
    recommendations: list[TestTypeRecommendation] = Field(default_factory=list)
    failed_segments: list[str] = Field(default_factory=list)
    trace_index: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_requirement_ids(self) -> "ParsedRequirements":
        identifiers = [item.id for item in self.requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("需求编号不能重复")
        if self.schema_version == "2.0":
            for item in self.requirements:
                if not (item.target.strip() and item.categories and item.description.strip()
                        and item.expected_behavior.strip() and item.confidence is not None
                        and item.source_evidence):
                    raise ValueError(f"{item.id}: v2 需求缺少对象、类别、规则、预期、置信度或来源")
                if any(not (s.segment_id and s.sha256 and s.locator) for s in item.source_evidence):
                    raise ValueError(f"{item.id}: v2 来源必须含片段、哈希与位置")
                if item.information_nature in {"historical", "assumption"}:
                    raise ValueError("历史补全和无依据假设不能进入正式需求")
                if item.information_nature == "derived" and not item.rationale.strip():
                    raise ValueError("推导需求必须说明依据")
            for issue in self.ambiguities + self.conflicts:
                if not set(issue.requirement_ids).issubset(identifiers):
                    raise ValueError("歧义或冲突引用了不存在的需求")
            for recommendation in self.recommendations:
                if not set(recommendation.requirement_ids).issubset(identifiers):
                    raise ValueError("测试类型推荐引用了不存在的需求")
        return self

    def legacy_payload(self) -> dict:
        """只允许旧版本导出旧字段，拒绝静默丢弃 S1 的来源和核验信息。"""
        if self.schema_version != "1.0":
            raise ValueError("v2 不允许有损降级；旧消费者须显式升级")
        payload = self.model_dump(mode="json", exclude_defaults=True)
        old_top = {"schema_version", "source", "requirements", "unresolved_fields", "warnings"}
        old_item = {"id", "title", "description", "requirement_type", "priority", "risk",
                    "acceptance_criteria", "constraints", "source_evidence"}
        old_ref = {"path", "sha256", "section", "page", "excerpt"}
        if set(payload) - old_top:
            raise ValueError("v1 含 S1 扩展字段，不能静默导出给旧消费者")
        for requirement in payload.get("requirements", []):
            if set(requirement) - old_item:
                raise ValueError("v1 需求含 S1 扩展字段，不能静默降级")
            for ref in requirement.get("source_evidence", []):
                if set(ref) - old_ref:
                    raise ValueError("v1 来源含 S1 扩展字段，不能静默降级")
        return payload | {"schema_version": "1.0"}

