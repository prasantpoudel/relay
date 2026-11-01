"""Task lifecycle.

A long generation must survive an MCP host restart, so every transition is written through to
SQLite and ``get`` can rebuild a task from disk.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from relay.daemon.tasks import TaskRegistry
from relay.drivers.base import AskResult
from relay.errors import QuotaExceeded


@pytest.fixture
def registry(tmp_path: Path) -> TaskRegistry:
    return TaskRegistry(db_path=tmp_path / "state.db")


def result(provider: str = "chatgpt") -> AskResult:
    return AskResult(
        provider=provider,
        text_markdown="**answer**",
        conversation_url="https://example.test/c/1",
        elapsed_ms=12,
    )


# --- creation --------------------------------------------------------------------------


def test_create_starts_pending(registry: TaskRegistry) -> None:
    task = registry.create("chatgpt")

    assert task.status == "pending"
    assert task.provider == "chatgpt"
    assert task.id


def test_ids_are_unique(registry: TaskRegistry) -> None:
    ids = {registry.create("chatgpt").id for _ in range(50)}

    assert len(ids) == 50


def test_create_is_visible_from_disk_immediately(registry: TaskRegistry) -> None:
    task = registry.create("gemini")

    found = registry.get(task.id)

    assert found is not None
    assert found.status == "pending"


# --- transitions -----------------------------------------------------------------------


async def test_complete_wakes_a_waiter(registry: TaskRegistry) -> None:
    task = registry.create("chatgpt")

    async def finish() -> None:
        await asyncio.sleep(0.01)
        registry.complete(task.id, result())

    finisher = asyncio.create_task(finish())
    done = await task.wait(timeout_s=1.0)
    await finisher

    assert done.status == "done"
    assert done.result is not None
    assert done.result.text_markdown == "**answer**"


async def test_fail_records_a_typed_error(registry: TaskRegistry) -> None:
    task = registry.create("gemini")

    registry.fail(task.id, QuotaExceeded("limit reached"))
    done = await task.wait(timeout_s=1.0)

    assert done.status == "error"
    assert done.error is not None
    assert done.error["code"] == "quota_exceeded"
    assert done.error["http_status"] == 429
    assert "limit reached" in done.error["message"]


async def test_unexpected_exception_becomes_an_internal_error(registry: TaskRegistry) -> None:
    task = registry.create("claude")

    registry.fail(task.id, RuntimeError("kaboom"))
    done = await task.wait(timeout_s=1.0)

    assert done.error is not None
    assert done.error["code"] == "internal_error"
    assert done.error["http_status"] == 500


async def test_wait_times_out_while_the_task_is_still_running(registry: TaskRegistry) -> None:
    task = registry.create("chatgpt")

    with pytest.raises(TimeoutError):
        await task.wait(timeout_s=0.02)


# --- persistence -----------------------------------------------------------------------


async def test_finished_task_survives_a_registry_restart(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    first = TaskRegistry(db_path=db)
    task = first.create("chatgpt")
    first.complete(task.id, result())

    restarted = TaskRegistry(db_path=db)
    found = restarted.get(task.id)

    assert found is not None
    assert found.status == "done"
    assert found.result is not None
    assert found.result.conversation_url == "https://example.test/c/1"


async def test_pending_task_from_a_dead_daemon_is_reported_lost(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    first = TaskRegistry(db_path=db)
    task = first.create("gemini")

    restarted = TaskRegistry(db_path=db)
    found = restarted.get(task.id)

    assert found is not None
    assert found.status == "error"
    assert found.error is not None
    assert found.error["code"] == "daemon_restarted"


def test_unknown_task_is_none(registry: TaskRegistry) -> None:
    assert registry.get("nope") is None


def test_drain_evicts_terminal_tasks_but_disk_still_answers(
    registry: TaskRegistry,
) -> None:
    """A long-lived daemon must not grow one Task object per generation forever."""
    ids = []
    for _ in range(12):
        task = registry.create("chatgpt")
        registry.complete(task.id, result())
        ids.append(task.id)

    assert registry.in_memory == 12
    registry.drain()
    assert registry.in_memory == 0

    found = registry.get(ids[0])
    assert found is not None
    assert found.status == "done"


def test_drain_never_evicts_an_unfinished_task(registry: TaskRegistry) -> None:
    task = registry.create("gemini")

    registry.drain()

    assert registry.in_memory == 1
    assert registry.get(task.id) is not None


# --- serialisation ---------------------------------------------------------------------


def test_task_dict_shape_is_stable(registry: TaskRegistry) -> None:
    task = registry.create("chatgpt")
    registry.complete(task.id, result())

    payload = task.to_dict()

    assert payload["status"] == "done"
    assert payload["provider"] == "chatgpt"
    assert payload["result"]["text_markdown"] == "**answer**"
    assert payload["error"] is None
