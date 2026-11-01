"""SQLite state. stdlib only — Python ships sqlite3, so no native build and no ORM.

Holds the small amount of state that must survive a restart: which providers are logged in, which
conversations belong to which workspace, live task records, and selector-drift counters.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .log import RELAY_HOME

DB_PATH = RELAY_HOME / "state.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    id           TEXT PRIMARY KEY,
    logged_in    INTEGER NOT NULL DEFAULT 0,
    last_checked REAL,
    last_error   TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id        TEXT PRIMARY KEY,
    provider  TEXT NOT NULL,
    url       TEXT NOT NULL,
    workspace TEXT,
    created   REAL NOT NULL,
    updated   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_provider ON conversations(provider, workspace);

CREATE TABLE IF NOT EXISTS tasks (
    id       TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    status   TEXT NOT NULL,
    created  REAL NOT NULL,
    updated  REAL NOT NULL,
    payload  TEXT
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);

-- Drift detector: a selector that keeps resolving at index > 0 means the UI moved.
CREATE TABLE IF NOT EXISTS selector_hits (
    provider TEXT NOT NULL,
    name     TEXT NOT NULL,
    idx      INTEGER NOT NULL,
    hits     INTEGER NOT NULL DEFAULT 0,
    updated  REAL NOT NULL,
    PRIMARY KEY (provider, name, idx)
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the state database, creating it if needed."""
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Connection that commits on success and always closes."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_selector_hit(conn: sqlite3.Connection, provider: str, name: str, idx: int) -> None:
    """Track which selector in the fallback chain matched.

    Index 0 is healthy. A rising index is the earliest warning that the provider changed its DOM.
    """
    conn.execute(
        """
        INSERT INTO selector_hits (provider, name, idx, hits, updated)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT (provider, name, idx)
        DO UPDATE SET hits = hits + 1, updated = excluded.updated
        """,
        (provider, name, idx, time.time()),
    )


def set_provider_state(
    conn: sqlite3.Connection,
    provider: str,
    *,
    logged_in: bool,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO providers (id, logged_in, last_checked, last_error)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            logged_in    = excluded.logged_in,
            last_checked = excluded.last_checked,
            last_error   = excluded.last_error
        """,
        (provider, int(logged_in), time.time(), error),
    )


def put_task(
    conn: sqlite3.Connection,
    task_id: str,
    provider: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO tasks (id, provider, status, created, updated, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET status = excluded.status, updated = excluded.updated,
                                       payload = excluded.payload
        """,
        (task_id, provider, status, now, now, json.dumps(payload) if payload else None),
    )


def get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return row
