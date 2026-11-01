"""Types crossing the driver boundary: they are persisted, so round-trips must be exact."""

from __future__ import annotations

from pathlib import Path

from relay.drivers.base import AskResult, Health


def test_ask_result_round_trips_through_json() -> None:
    original = AskResult(
        provider="chatgpt",
        text_markdown="**hi**",
        conversation_url="https://chatgpt.com/c/1",
        model="gpt-x",
        images=[Path("/tmp/a.png")],
        elapsed_ms=42,
        truncated=True,
        quota_note="resets at 18:00",
    )

    restored = AskResult.from_dict(original.to_dict())

    assert restored == original


def test_result_is_marked_untrusted_by_default() -> None:
    result = AskResult(provider="gemini", text_markdown="x", conversation_url="u")

    assert result.to_dict()["untrusted"] is True


def test_health_serialises_to_a_plain_dict() -> None:
    payload = Health(provider="claude", reachable=True, logged_in=False, detail="sign in").to_dict()

    assert payload == {
        "provider": "claude",
        "reachable": True,
        "logged_in": False,
        "detail": "sign in",
    }
