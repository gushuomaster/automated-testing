from __future__ import annotations

from datetime import timedelta
from typing import Protocol
from uuid import UUID

from testing_platform.domain.tasks import WorkflowTask


class TaskRepository(Protocol):
    def create(self, task: WorkflowTask) -> WorkflowTask: ...

    def get(self, task_id: UUID) -> WorkflowTask | None: ...

    def save(self, task: WorkflowTask) -> WorkflowTask: ...

    def claim_next(
        self,
        worker_id: str,
        lease_timeout: timedelta,
    ) -> WorkflowTask | None: ...

