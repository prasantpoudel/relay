"""The happy path: navigate, insert, wait, extract, remember."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from relay.drivers.base import Selectors
from tests.fakes import FakePage


async def test_fresh_ask_opens_a_new_chat(provider: Any, page: FakePage, ask: Any) -> None:
    result = await provider.ask(ask())

    assert page.goto_calls == ["https://example.test/new"]
    assert result.text_markdown == "Hello"
    assert result.conversation_url == "https://example.test/new"
    assert result.provider == "test"
    assert result.untrusted is True


async def test_existing_conversation_is_opened(provider: Any, page: FakePage, ask: Any) -> None:
    await provider.ask(ask(new_chat=False, conversation_url="https://example.test/c/abc"))

    assert page.goto_calls == ["https://example.test/c/abc"]


async def test_text_is_inserted_as_one_keyboard_event(
    provider: Any, page: FakePage, ask: Any
) -> None:
    await provider.ask(ask("say OK"))

    assert page.keyboard.typed == ["say OK"]
    assert "Enter" in page.keyboard.pressed


async def test_an_answer_that_never_settles_is_truncated(
    provider: Any, page: FakePage, ask: Any
) -> None:
    page.never_settles = True

    result = await provider.ask(ask(settle_timeout_s=0.15))

    assert result.truncated is True
    assert result.text_markdown.startswith("x")


# --- state -----------------------------------------------------------------------------


async def test_conversation_is_remembered(provider: Any, db_path: Path, ask: Any) -> None:
    await provider.ask(ask())

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT provider, url FROM conversations").fetchall()

    assert rows == [("test", "https://example.test/new")]


async def test_composer_hit_is_recorded_at_index_zero(
    provider: Any, db_path: Path, ask: Any
) -> None:
    await provider.ask(ask())

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name, idx, hits FROM selector_hits WHERE provider = 'test'"
        ).fetchall()

    assert ("composer", 0, 1) in rows


async def test_fallback_selector_is_recorded_as_drift(
    provider: Any, db_path: Path, ask: Any
) -> None:
    provider.selectors = Selectors(
        {
            **{name: provider.selectors.get(name) for name in provider.selectors.names()},
            "composer": ["#gone", "#composer"],
        }
    )

    await provider.ask(ask())

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT idx FROM selector_hits WHERE name = 'composer'").fetchall()

    assert (1,) in rows
