"""Tests for the foundation layer: errors, logging, state.

No network, no browser, no logged-in account — the rule from AGENTS.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from relay import errors
from relay.util import state
from relay.util.log import get_logger

# --- errors ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        errors.ProviderUnavailable,
        errors.NotLoggedIn,
        errors.QuotaExceeded,
        errors.SendFailed,
        errors.GenerationTimeout,
    ],
)
def test_every_error_carries_a_code_and_status(exc: type[errors.RelayError]) -> None:
    assert exc.code
    assert 400 <= exc.http_status <= 599


def test_selector_miss_names_the_provider_and_the_selector() -> None:
    err = errors.SelectorMiss("gemini", "composer", ["a", "b", "c"])

    message = str(err)
    assert "gemini" in message
    assert "composer" in message
    assert "3 selectors" in message
    assert err.http_status == 502


def test_all_errors_share_one_base_class() -> None:
    assert issubclass(errors.SelectorMiss, errors.RelayError)


# --- logging --------------------------------------------------------------------------


def test_logger_never_writes_to_stdout(capfd: pytest.CaptureFixture[str]) -> None:
    """stdout is the MCP JSON-RPC channel. Anything written there breaks the host."""
    get_logger("test").info("hello from the test")

    out, err = capfd.readouterr()
    assert out == ""
    assert "hello from the test" in err


# --- state ----------------------------------------------------------------------------


def test_task_round_trips_through_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "state.db"

    with state.session(db) as conn:
        state.put_task(conn, "task-1", "chatgpt", "pending")

    with state.session(db) as conn:
        row = state.get_task(conn, "task-1")

    assert row is not None
    assert row["provider"] == "chatgpt"
    assert row["status"] == "pending"


def test_task_status_update_overwrites_in_place(tmp_path: Path) -> None:
    db = tmp_path / "state.db"

    with state.session(db) as conn:
        state.put_task(conn, "task-1", "chatgpt", "pending")
        state.put_task(conn, "task-1", "chatgpt", "done", {"text": "ok"})

    with state.session(db) as conn:
        rows = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()
        row = state.get_task(conn, "task-1")

    assert rows["n"] == 1
    assert row is not None
    assert row["status"] == "done"
    assert '"ok"' in row["payload"]


def test_selector_hits_accumulate_per_index(tmp_path: Path) -> None:
    """Index 0 is healthy. Rising indices are the drift signal, so they must stay separate."""
    db = tmp_path / "state.db"

    with state.session(db) as conn:
        state.record_selector_hit(conn, "chatgpt", "composer", 0)
        state.record_selector_hit(conn, "chatgpt", "composer", 0)
        state.record_selector_hit(conn, "chatgpt", "composer", 2)

    with state.session(db) as conn:
        rows = conn.execute("SELECT idx, hits FROM selector_hits ORDER BY idx").fetchall()

    assert [(r["idx"], r["hits"]) for r in rows] == [(0, 2), (2, 1)]


def test_provider_state_can_be_marked_logged_out(tmp_path: Path) -> None:
    db = tmp_path / "state.db"

    with state.session(db) as conn:
        state.set_provider_state(conn, "gemini", logged_in=True)
        state.set_provider_state(conn, "gemini", logged_in=False, error="session expired")

    with state.session(db) as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = 'gemini'").fetchone()

    assert row is not None
    assert row["logged_in"] == 0
    assert row["last_error"] == "session expired"
