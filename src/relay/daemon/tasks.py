"""Task lifecycle, written through to SQLite.

The rule: a generation that takes four minutes must survive the MCP host restarting. So every
transition is persisted, and ``get`` can rebuild a terminal task from disk with no in-memory state.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..drivers.base import AskResult
from ..errors import RelayError
from ..util import state
from ..util.log import get_logger

log = get_logger("tasks")

TaskStatus = Literal["pending", "running", "done", "error"]
_TERMINAL: frozenset[str] = frozenset({"done", "error"})


@dataclass(slots=True)
class TaskRecord:
    id: str
    provider: str
    status: TaskStatus
    created: float
    updated: float
    result: AskResult | None = None
    error: dict[str, Any] | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL

    async def wait(self, timeout_s: float) -> TaskRecord:
        """Block until the task finishes, or raise ``TimeoutError``."""
        if self.terminal:
            return self
        await asyncio.wait_for(self._event.wait(), timeout_s)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.id,
            "provider": self.provider,
            "status": self.status,
            "created": self.created,
            "updated": self.updated,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


class TaskRegistry:
    """Hot tasks in memory, every transition on disk."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._tasks: dict[str, TaskRecord] = {}

    @property
    def in_memory(self) -> int:
        return len(self._tasks)

    def create(self, provider: str) -> TaskRecord:
        now = time.time()
        task = TaskRecord(
            id=uuid.uuid4().hex[:16],
            provider=provider,
            status="pending",
            created=now,
            updated=now,
        )
        self._tasks[task.id] = task
        self._persist(task)
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        return self._load(task_id)

    def running(self, task_id: str) -> None:
        self._transition(task_id, "running")

    def complete(self, task_id: str, result: AskResult) -> None:
        task = self._require(task_id)
        task.result = result
        task.error = None
        task.status = "done"
        task.updated = time.time()
        task._event.set()
        self._persist(task)

    def fail(self, task_id: str, exc: BaseException) -> None:
        task = self._require(task_id)
        task.status = "error"
        task.error = _error_payload(exc)
        task.updated = time.time()
        task._event.set()
        self._persist(task)
        log.info("task %s failed: %s", task_id, task.error["code"])

    def drain(self) -> None:
        """Drop finished tasks from memory. Disk still answers ``get``."""
        for task_id in [tid for tid, task in self._tasks.items() if task.terminal]:
            del self._tasks[task_id]

    # --- internals ---------------------------------------------------------------------

    def _require(self, task_id: str) -> TaskRecord:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _transition(self, task_id: str, status: TaskStatus) -> None:
        task = self._require(task_id)
        if task.terminal:
            return
        task.status = status
        task.updated = time.time()
        self._persist(task)

    def _load(self, task_id: str) -> TaskRecord | None:
        with state.session(self._db_path) as conn:
            row = state.get_task(conn, task_id)
        if row is None:
            return None

        payload: dict[str, Any] = json.loads(row["payload"]) if row["payload"] else {}
        status: str = row["status"]

        if status not in ("pending", "running", "done", "error"):
            status = "error"

        if status in ("pending", "running"):
            # The process that owned this task is gone; it will never finish now.
            record = TaskRecord(
                id=row["id"],
                provider=row["provider"],
                status="error",
                created=row["created"],
                updated=row["updated"],
                error={
                    "code": "daemon_restarted",
                    "message": "the daemon restarted while this task was running; ask again",
                    "http_status": 503,
                },
            )
        else:
            result_payload = payload.get("result")
            record = TaskRecord(
                id=row["id"],
                provider=row["provider"],
                status=status,  # type: ignore[arg-type]
                created=row["created"],
                updated=row["updated"],
                result=AskResult.from_dict(result_payload) if result_payload else None,
                error=payload.get("error"),
            )

        self._tasks[record.id] = record
        return record

    def _persist(self, task: TaskRecord) -> None:
        payload: dict[str, Any] = {}
        if task.result is not None:
            payload["result"] = task.result.to_dict()
        if task.error is not None:
            payload["error"] = task.error

        with state.session(self._db_path) as conn:
            state.put_task(conn, task.id, task.provider, task.status, payload if payload else None)


def _error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, RelayError):
        return {"code": exc.code, "message": str(exc), "http_status": exc.http_status}
    return {
        "code": "internal_error",
        "message": str(exc) or type(exc).__name__,
        "http_status": 500,
    }


__all__ = ["TaskRecord", "TaskRegistry", "TaskStatus"]
