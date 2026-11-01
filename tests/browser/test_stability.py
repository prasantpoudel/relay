"""The completion detector: text stops changing, or the deadline wins."""

from __future__ import annotations

from typing import Any

from relay.browser import dom


async def test_returns_once_the_text_stops_changing() -> None:
    script = iter(["a", "ab", "abc", "abc", "abc"])

    text, timed_out = await dom.stable_text(
        _async(lambda: next(script, "abc")), min_stable_s=0.02, poll_s=0.01, timeout_s=2
    )

    assert text == "abc"
    assert timed_out is False


async def test_times_out_when_text_never_settles() -> None:
    counter = {"n": 0}

    def growing() -> str:
        counter["n"] += 1
        return "x" * counter["n"]

    text, timed_out = await dom.stable_text(
        _async(growing), min_stable_s=1.0, poll_s=0.01, timeout_s=0.1
    )

    assert timed_out is True
    assert text.startswith("x")


async def test_empty_text_never_counts_as_settled() -> None:
    text, timed_out = await dom.stable_text(
        _async(lambda: ""), min_stable_s=0.01, poll_s=0.01, timeout_s=0.1
    )

    assert text == ""
    assert timed_out is True


def _async(fn: Any) -> Any:
    async def wrapper() -> str:
        return str(fn())

    return wrapper
