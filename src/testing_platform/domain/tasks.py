from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from testing_platform.domain.test_design import TestDesignPackage


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskType(StrEnum):
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    DESIGN = "design"
    EXECUTE = "execute"
    PIPELINE = "pipeline"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_REVIEW = "waiting_for_review"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(StrEnum):
    QUEUED = "queued"
    REQUIREMENTS_VALIDATED = "requirements_validated"
    DOCUMENTS_INGESTED = "documents_ingested"
    REQUIREMENTS_ANALYZED = "requirements_analyzed"
    REQUIREMENTS_VERIFIED = "requirements_verified"
    DESIGN_COMPLETED = "design_completed"
    EXECUTION_STARTED = "execution_started"
    CASE_COMPLETED = "case_completed"
    EXECUTION_COMPLETED = "execution_completed"
    REPORT_COMPLETED = "report_completed"


class ArtifactKind(StrEnum):
    INPUT = "input"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    TEST_DESIGN = "test_design"
    EXECUTION_RESULT = "execution_result"
    EXECUTION_BATCH = "execution_batch"
    TEST_REPORT = "test_report"
    LOG = "log"
    OTHER = "other"


class WorkflowErrorCode(StrEnum):
    INVALID_TASK = "INVALID_TASK"
    HANDLER_NOT_FOUND = "HANDLER_NOT_FOUND"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    WORKER_INTERRUPTED = "WORKER_INTERRUPTED"


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    kind: ArtifactKind
    uri: str
    name: str
    media_type: str = "application/octet-stream"
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements_text: str = ""
    runner_name: str = "agent-browser"
    max_cases: int = Field(default=20, gt=0)
    stop_on_failure: bool = False
    base_url: str | None = None
    timeout_seconds: int = Field(default=300, gt=0)
    max_retries: int = Field(default=0, ge=0)
    design_package: TestDesignPackage | None = None


class WorkflowError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: WorkflowErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    stage: WorkflowStage
    created_at: datetime = Field(default_factory=utc_now)
    case_id: str | None = None
    message: str = ""
    artifact_ids: list[UUID] = Field(default_factory=list)


class WorkflowTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    id: UUID = Field(default_factory=uuid4)
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    current_stage: WorkflowStage = WorkflowStage.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    worker_id: str | None = None
    input: WorkflowTaskInput
    input_artifacts: list[ArtifactReference] = Field(default_factory=list)
    output_artifacts: list[ArtifactReference] = Field(default_factory=list)
    checkpoints: list[WorkflowCheckpoint] = Field(default_factory=list)
    error: WorkflowError | None = None
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "WorkflowTask":
        if self.finished_at and self.started_at and self.finished_at < self.started_at:
            raise ValueError("任务结束时间不能早于开始时间")
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        if self.status in terminal and self.finished_at is None:
            raise ValueError("终态任务必须包含结束时间")
        if self.status == TaskStatus.COMPLETED and self.error is not None:
            raise ValueError("已完成任务不能包含错误")
        sequences = [item.sequence for item in self.checkpoints]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Checkpoint sequence 必须从 1 连续递增")
        return self

