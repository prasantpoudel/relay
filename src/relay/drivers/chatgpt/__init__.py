"""ChatGPT's web surface."""

from __future__ import annotations

from pathlib import Path

from ..browser_provider import BrowserProvider


class ChatGPT(BrowserProvider):
    id = "chatgpt"
    home_url = "https://chatgpt.com/"
    new_chat_url = "https://chatgpt.com/"
    selectors_file = Path(__file__).with_name("selectors.json")


__all__ = ["ChatGPT"]
