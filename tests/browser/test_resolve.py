"""Ordered fallback resolution. The returned index is the drift signal."""

from __future__ import annotations

import pytest

from relay.browser import dom
from relay.errors import SelectorMiss
from tests.browser.stubs import StubLocator, StubPage


async def test_returns_first_visible_match_at_index_zero() -> None:
    page = StubPage({"#a": StubLocator()})

    locator, index = await dom.resolve(page, ["#a", "#b"], provider="x", name="composer")  # type: ignore[arg-type]

    assert index == 0
    assert locator is page.mapping["#a"]


async def test_reports_the_fallback_index_that_matched() -> None:
    page = StubPage({"#b": StubLocator()})

    _, index = await dom.resolve(page, ["#a", "#b"], provider="x", name="composer")  # type: ignore[arg-type]

    assert index == 1


async def test_skips_hidden_candidates() -> None:
    page = StubPage({"#a": StubLocator(visible=False), "#b": StubLocator()})

    _, index = await dom.resolve(page, ["#a", "#b"], provider="x", name="composer")  # type: ignore[arg-type]

    assert index == 1


async def test_names_the_provider_and_every_selector_it_tried() -> None:
    with pytest.raises(SelectorMiss) as caught:
        await dom.resolve(
            StubPage({}),
            ["#a", "#b"],
            provider="gemini",
            name="composer",
            timeout_ms=10,  # type: ignore[arg-type]
        )

    assert caught.value.provider == "gemini"
    assert caught.value.tried == ["#a", "#b"]


async def test_rejects_an_empty_chain() -> None:
    with pytest.raises(SelectorMiss):
        await dom.resolve(StubPage({}), [], provider="x", name="composer")  # type: ignore[arg-type]
