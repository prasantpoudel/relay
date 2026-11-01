"""DOM primitives. The only module that touches a page.

Three verbs, no provider knowledge:

- ``resolve``      walk an ordered selector list, return the first visible match *and its index*
- ``insert_text``  put text in a composer the way every provider's editor accepts
- ``stable_text``  poll a text getter until it stops changing

``browser/`` must never import from ``drivers/``. This module knows about locators and text; it does
not know that ChatGPT or Gemini exist.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from ..errors import SelectorMiss, SendFailed
from ..util.log import get_logger

log = get_logger("dom")

# How long to wait for text we just inserted to appear in the composer. Editors apply it on a
# microtask, so this is generous rather than slow.
_SETTLE_MS = 2_000


async def resolve(
    page: Page,
    candidates: Sequence[str],
    *,
    provider: str = "unknown",
    name: str = "selector",
    timeout_ms: float = 15_000,
    poll_s: float = 0.25,
) -> tuple[Locator, int]:
    """Return the first visible match and its index in ``candidates``.

    The index is the drift signal: 0 is healthy, anything higher means a fallback is carrying the
    provider and the primary selector should be repaired.
    """
    if not candidates:
        raise SelectorMiss(provider, name, list(candidates))

    deadline = time.monotonic() + timeout_ms / 1000

    while True:
        for index, selector in enumerate(candidates):
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                if await locator.is_visible():
                    if index:
                        log.debug("%s: '%s' resolved at fallback index %d", provider, name, index)
                    return locator, index
            except PlaywrightError:
                # A selector can be invalid for the current document, or the page can navigate
                # mid-check. Both are "this candidate did not match"; keep walking.
                continue

        if time.monotonic() >= deadline:
            raise SelectorMiss(provider, name, list(candidates))
        await asyncio.sleep(poll_s)


async def composer_text(composer: Locator) -> str:
    """Read the current composer contents, for both contenteditable and textarea inputs."""
    try:
        value: Any = await composer.evaluate(
            "(el) => (typeof el.value === 'string' ? el.value"
            " : (el.innerText || el.textContent || ''))"
        )
    except PlaywrightError:
        return ""
    return value if isinstance(value, str) else ""


async def insert_text(
    page: Page, composer: Locator, text: str, *, settle_ms: float | None = None
) -> None:
    """Insert text so ProseMirror, rich-textarea and contenteditable editors all accept it.

    ``keyboard.insert_text`` dispatches an IME-style insertion through CDP. Assigning ``value`` or
    calling ``fill`` is silently ignored by ChatGPT, Gemini and Claude alike.

    Raises ``SendFailed`` if the composer stays empty after both attempts — that is the signal that
    the editor rejected the input, not that the model is slow.
    """
    budget = _SETTLE_MS if settle_ms is None else settle_ms

    await composer.click()
    await page.keyboard.insert_text(text)

    if await _text_landed(composer, budget):
        return

    log.warning("insert_text produced an empty composer; retrying via execCommand")
    await composer.evaluate(
        "(el, t) => { el.focus(); document.execCommand('insertText', false, t); }",
        text,
    )

    if await _text_landed(composer, budget):
        return

    raise SendFailed(
        "the composer stayed empty after inserting text. The editor rejected the input; "
        "the provider likely changed its UI — run `relay doctor`."
    )


async def _text_landed(composer: Locator, settle_ms: float) -> bool:
    deadline = time.monotonic() + settle_ms / 1000
    while time.monotonic() < deadline:
        if (await composer_text(composer)).strip():
            return True
        await asyncio.sleep(0.05)
    return False


async def clear_composer(page: Page, composer: Locator) -> None:
    """Select-all and delete. Used before a single retry, never between streamed tokens."""
    await composer.click()
    await page.keyboard.press("Meta+A" if sys.platform == "darwin" else "Control+A")
    await page.keyboard.press("Backspace")


async def insert_and_send(
    page: Page, composer: Locator, text: str, *, settle_ms: float | None = None
) -> None:
    """Insert, verify, then submit with a real Enter key event."""
    await insert_text(page, composer, text, settle_ms=settle_ms)
    await page.keyboard.press("Enter")


async def stable_text(
    get_text: Callable[[], Awaitable[str]],
    *,
    min_stable_s: float = 1.2,
    poll_s: float = 0.4,
    timeout_s: float = 600.0,
) -> tuple[str, bool]:
    """Poll until the text stops changing, and return ``(text, timed_out)``.

    Deliberately signal-free: it does not know about stop buttons or spinners, because those differ
    per provider. The driver supplies whatever stream-status check it has.
    """
    deadline = time.monotonic() + timeout_s
    last = await get_text()
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        await asyncio.sleep(poll_s)
        current = await get_text()

        if current != last:
            last = current
            stable_since = time.monotonic()
            continue

        if current.strip() and time.monotonic() - stable_since >= min_stable_s:
            return current, False

    return last, True


__all__ = [
    "clear_composer",
    "composer_text",
    "insert_and_send",
    "insert_text",
    "resolve",
    "stable_text",
]
