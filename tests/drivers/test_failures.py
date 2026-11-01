"""Failure paths. Each one must be a typed error naming the next action."""

from __future__ import annotations

from typing import Any

import pytest

from relay.drivers.base import Selectors
from relay.errors import NotLoggedIn, QuotaExceeded, SelectorMiss, SendFailed
from tests.fakes import FakePage


async def test_signed_out_raises_not_logged_in(provider: Any, page: FakePage, ask: Any) -> None:
    page.logged_out = True

    with pytest.raises(NotLoggedIn, match="relay login test"):
        await provider.ask(ask())


async def test_missing_composer_raises_selector_miss(provider: Any, ask: Any) -> None:
    provider.selectors = Selectors(
        {"composer": ["#nope", "#also-nope"], "assistant_turn": ["#assistant"]}
    )

    with pytest.raises(SelectorMiss) as caught:
        await provider.ask(ask())

    assert caught.value.name == "composer"
    assert caught.value.tried == ["#nope", "#also-nope"]


async def test_no_assistant_turn_raises_send_failed(
    provider: Any, page: FakePage, ask: Any
) -> None:
    page.respond = False

    with pytest.raises(SendFailed, match="test"):
        await provider.ask(ask())


async def test_rejected_input_is_retried_once_then_succeeds(
    provider: Any, page: FakePage, ask: Any
) -> None:
    page.reject_inserts = 1

    result = await provider.ask(ask())

    assert page.keyboard.typed == ["hi", "hi"]
    assert "Meta+A" in page.keyboard.pressed or "Control+A" in page.keyboard.pressed
    assert result.text_markdown == "Hello"


async def test_quota_banner_wins_over_a_generic_send_failure(
    provider: Any, page: FakePage, ask: Any
) -> None:
    """If the limit dialog is up, 'the send failed' is the wrong diagnosis."""
    page.respond = False
    page.quota = True

    with pytest.raises(QuotaExceeded):
        await provider.ask(ask())
