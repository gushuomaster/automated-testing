from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import tempfile

import pytest
from pydantic import ValidationError

from testing_platform.application.services.runner_registry import (
    RunnerRegistry,
    UnknownRunnerError,
)
from testing_platform.application.services.task_service import TaskService
from testing_platform.application.services.task_worker import (
    RetryableTaskError,
    TaskWorker,
)
from testing_platform.domain.execution import ExecutionContext
from testing_platform.domain.requirements import (
    ParsedRequirements,
    RequirementItem,
    SourceDocument,
)
from testing_platform.domain.tasks import (
    ArtifactKind,
    TaskStatus,
    TaskType,
    WorkflowTaskInput,
)
from testing_platform.infrastructure.artifacts.local_artifact_store import (
    LocalArtifactStore,
)
from testing_platform.infrastructure.persistence.sqlite_task_repository import (
    ConcurrentTaskUpdateError,
    SQLiteTaskRepository,
)
from testing_platform.ports.agent_gateway import AgentResponse, AgentRunStatus


class FlakyHandler:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, task, context):
        self.calls += 1
        if self.calls == 1:
            raise RetryableTaskError("temporary model outage")
        return []


def test_requirement_model_preserves_schema_and_rejects_duplicate_ids() -> None:
    parsed = ParsedRequirements(
        source=SourceDocument(path="需求.md", sha256="abc"),
        requirements=[RequirementItem(id="REQ-001", title="登录")],
    )

    assert parsed.schema_version == "1.0"
    assert ParsedRequirements.model_validate_json(parsed.model_dump_json()) == parsed
    with pytest.raises(ValidationError, match="需求编号不能重复"):
        ParsedRequirements(
            source=SourceDocument(path="需求.md"),
            requirements=[
                RequirementItem(id="REQ-001"),
                RequirementItem(id="REQ-001"),
            ],
        )


def test_agent_response_mapping_keeps_stable_gateway_contract() -> None:
    response = AgentResponse.from_mapping(
        {
            "final_response": '{"requirements":[]}',
            "failed": False,
            "provider": "fake-provider",
            "model": "fake-model",
        }
    )

    assert response.status == AgentRunStatus.SUCCEEDED
    assert response.content == '{"requirements":[]}'
    assert response.provider == "fake-provider"
    assert response.model == "fake-model"
    assert isinstance(response.raw_response, dict)


def test_task_repository_uses_optimistic_locking() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repository = SQLiteTaskRepository(Path(temp_dir) / "tasks.db")
        task = TaskService(repository).create(
            TaskType.PIPELINE,
            WorkflowTaskInput(requirements_text="登录需求"),
        )
        first_copy = repository.get(task.id)
        second_copy = repository.get(task.id)
        assert first_copy is not None
        assert second_copy is not None
        repository.save(first_copy)

        with pytest.raises(ConcurrentTaskUpdateError):
            repository.save(second_copy)


def test_worker_retries_without_losing_task_identity() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repository = SQLiteTaskRepository(Path(temp_dir) / "tasks.db")
        task = TaskService(repository).create(
            TaskType.PIPELINE,
            WorkflowTaskInput(requirements_text="重试需求"),
            max_attempts=2,
        )
        handler = FlakyHandler()
        worker = TaskWorker(
            repository,
            {TaskType.PIPELINE: handler},
            "worker-retry",
            lease_timeout=timedelta(seconds=0),
        )

        first_attempt = worker.run_once()
        second_attempt = worker.run_once()

    assert first_attempt is not None
    assert second_attempt is not None
    assert first_attempt.status == TaskStatus.RETRYING
    assert second_attempt.status == TaskStatus.COMPLETED
    assert second_attempt.id == task.id
    assert second_attempt.attempt_count == 2


def test_artifact_store_writes_utf8_json_inside_configured_root() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = LocalArtifactStore(Path(temp_dir) / "artifacts")
        repository = SQLiteTaskRepository(Path(temp_dir) / "tasks.db")
        task = TaskService(repository).create(
            TaskType.DESIGN,
            WorkflowTaskInput(requirements_text="中文需求"),
        )

        artifact = store.put_json(
            task.id,
            "result.json",
            {"message": "中文可追溯"},
            ArtifactKind.OTHER,
        )
        resolved = store.resolve(artifact)

        assert resolved.is_file()
        assert "中文可追溯" in resolved.read_text(encoding="utf-8")
        assert artifact.sha256
        assert resolved.is_relative_to(Path(temp_dir).resolve())


def test_runner_registry_preserves_registration_contract() -> None:
    registry = RunnerRegistry()
    runner = object()
    registry.register("fake", runner)

    assert registry.get("fake") is runner
    assert registry.names() == ("fake",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("fake", runner)
    with pytest.raises(UnknownRunnerError):
        registry.get("missing")

    class Factory:
        def create(self, context):
            return {"run_id": context.run_id}

    registry.register_factory("factory", Factory())
    with tempfile.TemporaryDirectory() as temp_dir:
        created = registry.create(
            "factory",
            ExecutionContext(
                run_id="run-1",
                artifact_directory=Path(temp_dir),
            ),
        )
    assert created == {"run_id": "run-1"}


def test_production_source_has_no_examples_runtime_dependency() -> None:
    source_root = Path(__file__).parents[2] / "src"
    forbidden = (
        "D:\\project\\agent\\examples",
        "D:/project/agent/examples",
        "..\\examples",
        "../examples",
    )

    violations = []
    for path in source_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        if any(value in content for value in forbidden):
            violations.append(path.relative_to(source_root).as_posix())

    assert violations == []
