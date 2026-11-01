"""Health, doctor and disposal — the routes the CLI maintainer uses."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tests.fakes import FakePage


async def test_health_reports_logged_in(provider: Any) -> None:
    health = await provider.health()

    assert health.reachable is True
    assert health.logged_in is True


async def test_health_reports_signed_out(provider: Any, page: FakePage) -> None:
    page.logged_out = True

    health = await provider.health()

    assert health.reachable is True
    assert health.logged_in is False


async def test_doctor_reports_each_selector_with_its_index(provider: Any) -> None:
    report = await provider.doctor()

    assert report["composer"] == {"ok": True, "index": 0, "optional": False}
    assert report["assistant_turn"]["ok"] is False
    assert report["assistant_turn"]["optional"] is True


async def test_doctor_records_the_indices_it_found(provider: Any, db_path: Path) -> None:
    await provider.doctor()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM selector_hits").fetchall()

    assert ("composer",) in rows


async def test_dispose_closes_the_page(provider: Any, page: FakePage, ask: Any) -> None:
    await provider.ask(ask())

    await provider.dispose()

    assert page.closed is True
