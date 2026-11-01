"""The error taxonomy: codes, HTTP mappings, one base class."""

from __future__ import annotations

import pytest

from relay import errors


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


def test_remote_failure_keeps_the_original_code() -> None:
    err = errors.RemoteFailure("quota_exceeded", "limit reached", 429)

    assert err.code == "quota_exceeded"
    assert err.http_status == 429
    assert str(err) == "limit reached"
