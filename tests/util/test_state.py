"""SQLite state: tasks, selector-drift counters, provider status, conversations."""

from __future__ import annotations

from pathlib import Path

from relay.util import state


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


def test_conversation_urls_are_upserted_not_duplicated(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    url = "https://chatgpt.com/c/abc"

    with state.session(db) as conn:
        state.put_conversation(conn, "chatgpt", url, workspace="relay")
        state.put_conversation(conn, "chatgpt", url, workspace="relay")

    with state.session(db) as conn:
        rows = conn.execute("SELECT id, provider, url FROM conversations").fetchall()

    assert len(rows) == 1
    assert rows[0]["url"] == url


def test_two_providers_with_the_same_url_stay_separate(tmp_path: Path) -> None:
    db = tmp_path / "state.db"

    with state.session(db) as conn:
        first = state.put_conversation(conn, "chatgpt", "https://example.test/c/1")
        second = state.put_conversation(conn, "claude", "https://example.test/c/1")

    assert first != second
