"""Google Gemini's web surface.

Gemini renders answers as a custom ``<model-response>`` element. The Markdown lives inside a
``.markdown`` subtree, so the generic turn extractor is pointed at it explicitly; the outer element
carries toolbar buttons that are not worth stripping in Markdown.
"""

from __future__ import annotations

from pathlib import Path

from ..browser_provider import BrowserProvider


class Gemini(BrowserProvider):
    id = "gemini"
    home_url = "https://gemini.google.com/app"
    new_chat_url = "https://gemini.google.com/app"
    content_selector = ".markdown"
    selectors_file = Path(__file__).with_name("selectors.json")


__all__ = ["Gemini"]
