from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentTaskType(StrEnum):
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    REQUIREMENT_SOURCE_REPAIR = "requirement_source_repair"
    REQUIREMENT_ANALYSIS_REPAIR = "requirement_analysis_repair"
    REQUIREMENT_RECONCILIATION = "requirement_reconciliation"
    REQUIREMENT_VERIFICATION = "requirement_verification"
    TEST_DESIGN = "test_design"
    TEST_DESIGN_REPAIR = "test_design_repair"
    TEST_REPORT = "test_report"
    TEST_REPORT_REPAIR = "test_report_repair"
    UI_TARS_INSTRUCTION = "ui_tars_instruction"
    UI_TARS_RESULT = "ui_tars_result"


class OutputSchemaName(StrEnum):
    PARSED_REQUIREMENTS = "ParsedRequirementsProposal"
    REQUIREMENT_CANDIDATE = "RequirementCandidate"
    REQUIREMENT_BASELINE = "RequirementBaseline"
    REQUIREMENT_RECONCILIATION = "RequirementReconciliation"
    VERIFICATION_RESULT = "VerificationResult"
    TEST_DESIGN_PROPOSAL = "TestDesignProposal"
    TEST_DESIGN_PACKAGE = "TestDesignPackage"
    TEST_REPORT_PROPOSAL = "TestReportProposal"
    TEST_REPORT = "TestReport"
    UI_TARS_INSTRUCTION = "UITARSInstruction"
    UI_TARS_EXECUTION_RESULT = "UITARSExecutionResult"


class AgentRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: AgentTaskType
    user_input: str
    system_context: str | None = None
    skill_name: str | None = None
    structured_input: dict[str, Any] | None = None
    output_schema: OutputSchemaName | None = None
    max_turns: int = Field(default=8, gt=0)
    metadata: dict[str, str] = Field(default_factory=dict)
    execution_mode: Literal["live", "export", "import"] = "live"
    model_id: str = ""
    skill_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)
    human_interventions: list[str] = Field(default_factory=list)


class AgentUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    status: str = ""
    duration_seconds: float | None = None


class AgentError(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    code: str = ""


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    content: str = ""
    structured_output: dict[str, Any] | None = None
    status: AgentRunStatus = AgentRunStatus.INCOMPLETE
    usage: AgentUsage | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    raw_response: Any = None
    error: AgentError | None = None
    provider: str = ""
    model: str = ""
    base_url: str = ""

    @classmethod
    def from_mapping(cls, result: Mapping[str, Any] | None) -> "AgentResponse":
        if result is None:
            return cls(
                status=AgentRunStatus.FAILED,
                error=AgentError(message="智能体没有返回有效结果。"),
            )
        content = str(result.get("final_response") or "").strip()
        failed = bool(result.get("failed"))
        error_message = str(result.get("error") or "")
        if failed:
            status = AgentRunStatus.FAILED
        elif content:
            status = AgentRunStatus.SUCCEEDED
        else:
            status = AgentRunStatus.INCOMPLETE
        return cls(
            content=content,
            status=status,
            raw_response=dict(result),
            error=AgentError(message=error_message) if error_message else None,
            provider=str(result.get("provider") or ""),
            model=str(result.get("model") or ""),
            base_url=str(result.get("base_url") or ""),
        )


class AgentGateway(Protocol):
    def run(self, request: AgentRequest) -> AgentResponse: ...


class AgentInputPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["agent-input/v1"]
    request: AgentRequest
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentRunAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["agent-run-audit/v1"]
    task_type: AgentTaskType
    execution_mode: Literal["live", "export", "import"]
    model_id: str
    provider: str
    skill_name: str
    skill_version: str
    parameters: dict[str, Any]
    attempt: int
    human_interventions: list[str]
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: AgentRunStatus
