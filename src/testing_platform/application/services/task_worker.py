from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol

from testing_platform.domain.tasks import (
    ArtifactReference,
    TaskStatus,
    TaskType,
    WorkflowCheckpoint,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowStage,
    WorkflowTask,
)
from testing_platform.ports.task_repository import TaskRepository


class TaskHandler(Protocol):
    def execute(
        self,
        task: WorkflowTask,
        context: "TaskExecutionContext",
    ) -> Sequence[ArtifactReference]: ...


class RetryableTaskError(RuntimeError):
    pass


class TaskExecutionContext:
    def __init__(
        self,
        task: WorkflowTask,
        repository: TaskRepository,
    ) -> None:
        self.task = task
        self._repository = repository

    def checkpoint(
        self,
        stage: WorkflowStage,
        *,
        case_id: str | None = None,
        message: str = "",
        artifacts: Sequence[ArtifactReference] = (),
    ) -> WorkflowTask:
        known_artifacts = {item.id for item in self.task.output_artifacts}
        new_artifacts = [
            item for item in artifacts if item.id not in known_artifacts
        ]
        checkpoint = WorkflowCheckpoint(
            sequence=len(self.task.checkpoints) + 1,
            stage=stage,
            case_id=case_id,
            message=message,
            artifact_ids=[item.id for item in artifacts],
        )
        self.task = self._repository.save(
            self.task.model_copy(
                update={
                    "current_stage": stage,
                    "heartbeat_at": datetime.now(timezone.utc),
                    "checkpoints": [*self.task.checkpoints, checkpoint],
                    "output_artifacts": [
                        *self.task.output_artifacts,
                        *new_artifacts,
                    ],
                }
            )
        )
        return self.task


class TaskWorker:
    def __init__(
        self,
        repository: TaskRepository,
        handlers: Mapping[TaskType, TaskHandler],
        worker_id: str,
        *,
        lease_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._handlers = dict(handlers)
        self._worker_id = worker_id
        self._lease_timeout = lease_timeout

    def run_once(self) -> WorkflowTask | None:
        task = self._repository.claim_next(
            self._worker_id,
            self._lease_timeout,
        )
        if task is None:
            return None

        context = TaskExecutionContext(task, self._repository)
        handler = self._handlers.get(task.task_type)
        if handler is None:
            return self._fail(
                context.task,
                WorkflowError(
                    code=WorkflowErrorCode.HANDLER_NOT_FOUND,
                    message=f"No handler registered for {task.task_type.value}",
                ),
            )

        try:
            artifacts = handler.execute(context.task, context)
            current = context.task
            known_artifacts = {item.id for item in current.output_artifacts}
            completed = current.model_copy(
                update={
                    "status": TaskStatus.COMPLETED,
                    "finished_at": datetime.now(timezone.utc),
                    "heartbeat_at": datetime.now(timezone.utc),
                    "output_artifacts": [
                        *current.output_artifacts,
                        *[
                            item
                            for item in artifacts
                            if item.id not in known_artifacts
                        ],
                    ],
                    "error": None,
                }
            )
            return self._repository.save(completed)
        except Exception as exc:
            retryable = isinstance(exc, RetryableTaskError)
            error = WorkflowError(
                code=WorkflowErrorCode.EXECUTION_FAILED,
                message=str(exc) or exc.__class__.__name__,
                retryable=retryable,
                details={"exception_type": exc.__class__.__name__},
            )
            current = context.task
            if retryable and current.attempt_count < current.max_attempts:
                retrying = current.model_copy(
                    update={
                        "status": TaskStatus.RETRYING,
                        "worker_id": None,
                        "heartbeat_at": None,
                        "error": error,
                    }
                )
                return self._repository.save(retrying)
            return self._fail(current, error)

    def _fail(
        self,
        task: WorkflowTask,
        error: WorkflowError,
    ) -> WorkflowTask:
        failed = task.model_copy(
            update={
                "status": TaskStatus.FAILED,
                "finished_at": datetime.now(timezone.utc),
                "heartbeat_at": datetime.now(timezone.utc),
                "error": error,
            }
        )
        return self._repository.save(failed)
