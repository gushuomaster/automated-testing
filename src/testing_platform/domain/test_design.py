from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .requirements import RequirementItem, SourceDocument


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] = Field(default_factory=dict)


class TestStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1)
    action: str = Field(min_length=1)
    expected_result: str | None = None


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = ""
    module: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: str = ""
    priority: str = ""
    test_type: str = ""
    test_data: str = ""
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_order(self) -> "TestCase":
        step_orders = [step.order for step in self.steps]
        if len(step_orders) != len(set(step_orders)):
            raise ValueError("测试步骤顺序不能重复")
        return self


class ExecutableTestCase(TestCase):
    entry_url: str | None = None


class TraceabilityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    case_ids: list[str] = Field(default_factory=list)


class TestDesignPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    source: SourceDocument | None = None
    plan: TestPlan = Field(default_factory=TestPlan)
    requirements: list[RequirementItem] = Field(default_factory=list)
    cases: list[TestCase] = Field(default_factory=list)
    traceability: list[TraceabilityEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identifiers_and_references(self) -> "TestDesignPackage":
        requirement_ids = [item.id for item in self.requirements]
        case_ids = [item.id for item in self.cases]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("需求编号不能重复")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("测试用例编号不能重复")

        known_requirements = set(requirement_ids)
        missing = sorted(
            {
                requirement_id
                for case in self.cases
                for requirement_id in case.requirement_ids
                if requirement_id not in known_requirements
            }
        )
        if missing:
            raise ValueError(f"测试用例引用了不存在的需求：{', '.join(missing)}")
        return self
