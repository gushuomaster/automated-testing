from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from testing_platform.domain.tasks import ArtifactKind, ArtifactReference


class ArtifactStore(Protocol):
    def workspace(self, task_id: UUID) -> Path: ...

    def put_json(
        self,
        task_id: UUID,
        name: str,
        payload: Any,
        kind: ArtifactKind,
    ) -> ArtifactReference: ...

    def resolve(self, artifact: ArtifactReference) -> Path: ...

