"""Typed failures.

Everything the bridge can fail with is one of these, so callers can branch on the class instead of
parsing strings. The MCP layer maps them to human-readable text; the daemon maps them to HTTP codes.
"""

from __future__ import annotations


class RelayError(Exception):
    """Base class for every error this package raises on purpose."""

    code = "relay_error"
    http_status = 500


class ProviderUnavailable(RelayError):
    """Provider cannot be reached at all — Chrome down, app not running, unknown provider id."""

    code = "provider_unavailable"
    http_status = 503


class NotLoggedIn(RelayError):
    """The surface is reachable but the user is signed out. Only the user can fix this."""

    code = "not_logged_in"
    http_status = 401


class QuotaExceeded(RelayError):
    """Free-tier message cap or rate limit was hit. Retrying will not help until it resets."""

    code = "quota_exceeded"
    http_status = 429


class SelectorMiss(RelayError):
    """None of the configured selectors matched. The provider's UI has moved."""

    code = "selector_miss"
    http_status = 502

    def __init__(self, provider: str, name: str, tried: list[str]) -> None:
        self.provider = provider
        self.name = name
        self.tried = tried
        super().__init__(
            f"{provider}: no match for '{name}' among {len(tried)} selectors. "
            f"The UI probably changed — run `relay doctor {provider}`."
        )


class SendFailed(RelayError):
    """Text was inserted but no assistant turn appeared. The composer rejected the input."""

    code = "send_failed"
    http_status = 502


class GenerationTimeout(RelayError):
    """The answer never settled before the deadline. Partial text may still be useful."""

    code = "timeout"
    http_status = 504
