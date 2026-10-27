from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from uuid import UUID

from testing_platform.domain.tasks import (
    TaskStatus,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowTask,
)
from testing_platform.ports.task_repository import TaskRepository


class ConcurrentTaskUpdateError(RuntimeError):
    pass


class SQLiteTaskRepository(TaskRepository):
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, task: WorkflowTask) -> WorkflowTask:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO workflow_tasks (
                    id, task_type, status, worker_id, heartbeat_at,
                    created_at, updated_at, version, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._row_values(task),
            )
        return task

    def get(self, task_id: UUID) -> WorkflowTask | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM workflow_tasks WHERE id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            return None
        return WorkflowTask.model_validate_json(row["payload"])

    def save(self, task: WorkflowTask) -> WorkflowTask:
        updated = task.model_copy(
            update={
                "updated_at": datetime.now(timezone.utc),
                "version": task.version + 1,
            }
        )
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE workflow_tasks
                SET task_type = ?, status = ?, worker_id = ?, heartbeat_at = ?,
                    updated_at = ?, version = ?, payload = ?
                WHERE id = ? AND version = ?
                """,
                (
                    updated.task_type.value,
                    updated.status.value,
                    updated.worker_id,
                    self._iso(updated.heartbeat_at),
                    self._iso(updated.updated_at),
                    updated.version,
                    updated.model_dump_json(),
                    str(updated.id),
                    task.version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentTaskUpdateError(
                    f"Task {task.id} was updated by another worker"
                )
        return updated

    def claim_next(
        self,
        worker_id: str,
        lease_timeout: timedelta,
    ) -> WorkflowTask | None:
        if not worker_id.strip():
            raise ValueError("worker_id cannot be empty")
        stale_before = datetime.now(timezone.utc) - lease_timeout
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT payload
                FROM workflow_tasks
                WHERE status IN (?, ?)
                   OR (
                       status = ?
                       AND (heartbeat_at IS NULL OR heartbeat_at < ?)
                )
                ORDER BY created_at, id
                """,
                (
                    TaskStatus.PENDING.value,
                    TaskStatus.RETRYING.value,
                    TaskStatus.RUNNING.value,
                    self._iso(stale_before),
                ),
            ).fetchall()
            for row in rows:
                task = WorkflowTask.model_validate_json(row["payload"])
                now = datetime.now(timezone.utc)
                if (
                    task.status == TaskStatus.RUNNING
                    and task.attempt_count >= task.max_attempts
                ):
                    exhausted = task.model_copy(
                        update={
                            "status": TaskStatus.FAILED,
                            "finished_at": now,
                            "heartbeat_at": now,
                            "updated_at": now,
                            "version": task.version + 1,
                            "error": WorkflowError(
                                code=WorkflowErrorCode.WORKER_INTERRUPTED,
                                message=(
                                    "Worker lease expired after the maximum "
                                    "number of attempts"
                                ),
                            ),
                        }
                    )
                    self._update_claimed(connection, task, exhausted)
                    continue

                claimed = task.model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "worker_id": worker_id,
                        "started_at": task.started_at or now,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "finished_at": None,
                        "attempt_count": task.attempt_count + 1,
                        "version": task.version + 1,
                    }
                )
                self._update_claimed(connection, task, claimed)
                connection.commit()
                return claimed

            connection.commit()
            return None
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS workflow_tasks (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    worker_id TEXT,
                    heartbeat_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_tasks_claim
                    ON workflow_tasks(status, heartbeat_at, created_at);
                """
            )

    def _update_claimed(
        self,
        connection: sqlite3.Connection,
        previous: WorkflowTask,
        updated: WorkflowTask,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE workflow_tasks
            SET status = ?, worker_id = ?, heartbeat_at = ?,
                updated_at = ?, version = ?, payload = ?
            WHERE id = ? AND version = ?
            """,
            (
                updated.status.value,
                updated.worker_id,
                self._iso(updated.heartbeat_at),
                self._iso(updated.updated_at),
                updated.version,
                updated.model_dump_json(),
                str(updated.id),
                previous.version,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrentTaskUpdateError(
                f"Task {previous.id} was claimed concurrently"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _row_values(cls, task: WorkflowTask) -> tuple[object, ...]:
        return (
            str(task.id),
            task.task_type.value,
            task.status.value,
            task.worker_id,
            cls._iso(task.heartbeat_at),
            cls._iso(task.created_at),
            cls._iso(task.updated_at),
            task.version,
            task.model_dump_json(),
        )

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None
