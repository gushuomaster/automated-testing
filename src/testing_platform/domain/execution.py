from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ERROR = "error"
    SKIPPED = "skipped"


class RunnerType(StrEnum):
    AGENT_BROWSER = "agent-browser"
    UI_TARS = "ui-tars"
    BROWSER_BATCH = "browser-batch"
    FAKE = "fake"


class ExecutionErrorKind(StrEnum):
    ASSERTION = "assertion"
    ENVIRONMENT = "environment"
    RUNNER = "runner"
    TIMEOUT = "timeout"
    INVALID_CASE = "invalid_case"
    MODEL = "model"
    TEST_DATA = "test_data"
    CANCELLED = "cancelled"


class ExecutionErrorCode(StrEnum):
    ASSERTION_FAILED = "ASSERTION_FAILED"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    RUNNER_ERROR = "RUNNER_ERROR"
    RUNNER_TIMEOUT = "RUNNER_TIMEOUT"
    RUNNER_EXCEPTION = "RUNNER_EXCEPTION"
    INVALID_CASE = "INVALID_CASE"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MISSING_TEST_DATA = "MISSING_TEST_DATA"
    CANCELLED = "CANCELLED"


class ExecutionBatchStatus(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    CANCELLED = "cancelled"


_STATUS_ALIASES = {
    "PASS": ExecutionStatus.PASSED,
    "PASSED": ExecutionStatus.PASSED,
    "通过": ExecutionStatus.PASSED,
    "FAIL": ExecutionStatus.FAILED,
    "FAILED": ExecutionStatus.FAILED,
    "失败": ExecutionStatus.FAILED,
    "BLOCKED": ExecutionStatus.BLOCKED,
    "阻塞": ExecutionStatus.BLOCKED,
    "ERROR": ExecutionStatus.ERROR,
    "错误": ExecutionStatus.ERROR,
    "SKIPPED": ExecutionStatus.SKIPPED,
    "未执行": ExecutionStatus.SKIPPED,
    "PENDING": ExecutionStatus.PENDING,
}


class ExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    path: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str | None = None


class ExecutionError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExecutionErrorKind
    code: ExecutionErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class StepExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_order: int = Field(ge=1)
    status: ExecutionStatus
    actual_result: str = ""
    error: ExecutionError | None = None
    evidence: list[ExecutionEvidence] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _STATUS_ALIASES.get(str(value).strip().upper(), value)


class TestExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    case_id: str
    runner_type: RunnerType
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime
    step_results: list[StepExecutionResult] = Field(default_factory=list)
    actual_result: str = ""
    error: ExecutionError | None = None
    evidence: list[ExecutionEvidence] = Field(default_factory=list)
    log_paths: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _STATUS_ALIASES.get(str(value).strip().upper(), value)

    @model_validator(mode="after")
    def validate_result(self) -> "TestExecutionResult":
        if self.finished_at < self.started_at:
            raise ValueError("执行结束时间不能早于开始时间")
        step_orders = [item.step_order for item in self.step_results]
        if len(step_orders) != len(set(step_orders)):
            raise ValueError("步骤执行结果的顺序不能重复")
        if self.status == ExecutionStatus.PASSED and self.error is not None:
            raise ValueError("通过的执行结果不能包含错误")
        if self.status == ExecutionStatus.ERROR and self.error is None:
            raise ValueError("执行错误结果必须包含结构化错误")
        return self


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    base_url: str | None = None
    timeout_seconds: int = Field(default=300, gt=0)
    max_retries: int = Field(default=0, ge=0)
    artifact_directory: Path
    environment: dict[str, str] = Field(default_factory=dict)


class ExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    blocked_cases: int = Field(ge=0)
    error_cases: int = Field(ge=0)
    skipped_cases: int = Field(ge=0)


class ExecutionBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    run_id: str
    runner_name: str
    status: ExecutionBatchStatus
    started_at: datetime
    finished_at: datetime
    results: list[TestExecutionResult] = Field(default_factory=list)
    unexecuted_case_ids: list[str] = Field(default_factory=list)
    stopped_early: bool = False
    summary: ExecutionSummary

    @model_validator(mode="after")
    def validate_batch(self) -> "ExecutionBatchResult":
        if self.finished_at < self.started_at:
            raise ValueError("批次结束时间不能早于开始时间")
        if self.summary.total_cases != len(self.results) + len(self.unexecuted_case_ids):
            raise ValueError("批次汇总数量与结果数量不一致")
        if self.stopped_early != bool(self.unexecuted_case_ids):
            raise ValueError("提前停止标记与未执行用例不一致")
        return self
