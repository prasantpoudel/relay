"""Provider registry.

Adding a provider means adding a package here and one line to ``build_providers``. Nothing outside
``drivers/<name>/`` should need editing; if it does, the seam is wrong.
"""

from __future__ import annotations

from .base import AskRequest, AskResult, Health, Provider, Selectors
from .browser_provider import BrowserProvider
from .chatgpt import ChatGPT
from .claude import Claude
from .gemini import Gemini

PROVIDER_IDS = ("chatgpt", "gemini", "claude")


def build_providers() -> dict[str, BrowserProvider]:
    """Construct every driver. Cheap: no browser is touched until ``ask`` or ``health``."""
    providers: list[BrowserProvider] = [ChatGPT(), Gemini(), Claude()]
    return {provider.id: provider for provider in providers}


def get_provider(provider_id: str) -> BrowserProvider:
    from ..errors import ProviderUnavailable

    providers = build_providers()
    try:
        return providers[provider_id]
    except KeyError:
        known = ", ".join(sorted(providers))
        raise ProviderUnavailable(
            f"unknown provider '{provider_id}'. Known providers: {known}."
        ) from None


__all__ = [
    "PROVIDER_IDS",
    "AskRequest",
    "AskResult",
    "BrowserProvider",
    "ChatGPT",
    "Claude",
    "Gemini",
    "Health",
    "Provider",
    "Selectors",
    "build_providers",
    "get_provider",
]
