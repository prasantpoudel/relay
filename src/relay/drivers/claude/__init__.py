"""Claude's web surface. Note: this is the target, not the host — relay talks to it like any other."""

from __future__ import annotations

from pathlib import Path

from ..browser_provider import BrowserProvider


class Claude(BrowserProvider):
    id = "claude"
    home_url = "https://claude.ai/new"
    new_chat_url = "https://claude.ai/new"
    selectors_file = Path(__file__).with_name("selectors.json")


__all__ = ["Claude"]
