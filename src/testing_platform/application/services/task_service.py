from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from testing_platform.domain.tasks import (
    ArtifactReference,
    TaskStatus,
    TaskType,
    WorkflowTask,
    WorkflowTaskInput,
)
from testing_platform.ports.task_repository import TaskRepository


class TaskNotFoundError(LookupError):
    pass


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def create(
        self,
        task_type: TaskType,
        task_input: WorkflowTaskInput,
        input_artifacts: list[ArtifactReference] | None = None,
        *,
        max_attempts: int = 1,
    ) -> WorkflowTask:
        task = WorkflowTask(
            task_type=task_type,
            input=task_input,
            input_artifacts=input_artifacts or [],
            max_attempts=max_attempts,
        )
        return self._repository.create(task)

    def get(self, task_id: UUID) -> WorkflowTask:
        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    def cancel(self, task_id: UUID) -> WorkflowTask:
        task = self.get(task_id)
        if task.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            return task
        cancelled = task.model_copy(
            update={
                "status": TaskStatus.CANCELLED,
                "finished_at": datetime.now(timezone.utc),
            }
        )
        return self._repository.save(cancelled)

