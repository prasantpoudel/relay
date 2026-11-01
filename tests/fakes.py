"""Fakes for the driver and daemon suites.

These stand in for Playwright and the network. Nothing here touches a browser, a socket or an
account — the rule from AGENTS.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from relay.drivers.base import AskResult, Health


class FakeLocator:
    def __init__(
        self,
        *,
        present: bool = True,
        visible: bool = True,
        text: str = "",
        html: str = "",
    ) -> None:
        self.present = present
        self.visible = visible
        self.text = text
        self.html = html
        self.clicks = 0
        self.exec_calls = 0

    @property
    def first(self) -> FakeLocator:
        return self

    @property
    def last(self) -> FakeLocator:
        return self

    async def count(self) -> int:
        return 1 if self.present else 0

    async def is_visible(self) -> bool:
        return self.present and self.visible

    async def inner_text(self) -> str:
        return self.text

    async def inner_html(self) -> str:
        return self.html or f"<p>{self.text}</p>"

    async def click(self) -> None:
        self.clicks += 1

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "execCommand" in script:
            self.exec_calls += 1
            return None
        return self.text

    def locator(self, selector: str) -> FakeLocator:
        return self


class FakeComposer(FakeLocator):
    """A contenteditable stand-in whose contents are written by the fake keyboard."""

    def __init__(self, page: FakePage) -> None:
        super().__init__()
        self.page = page

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "execCommand" in script:
            self.exec_calls += 1
            return None
        return self.text


class FakeTurn(FakeLocator):
    def __init__(self, page: FakePage) -> None:
        super().__init__(present=False)
        self.page = page

    async def count(self) -> int:
        return 1 if self.page.sent and self.page.respond else 0

    async def is_visible(self) -> bool:
        return bool(await self.count())

    async def inner_text(self) -> str:
        return self.page.next_text()

    async def inner_html(self) -> str:
        return f"<p>{self.page.peek_text()}</p>"


class FakeKeyboard:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.typed: list[str] = []
        self.pressed: list[str] = []

    async def insert_text(self, text: str) -> None:
        self.typed.append(text)
        if self.page.reject_inserts > 0:
            self.page.reject_inserts -= 1
            return
        self.page.composer.text = text

    async def press(self, key: str) -> None:
        self.pressed.append(key)
        if key == "Enter":
            self.page.sent = True
            self.page.polls = 0


class FakePage:
    """Just enough of ``playwright.async_api.Page`` for the ask flow."""

    def __init__(self, *, stream: tuple[str, ...] = ("Hel", "Hello", "Hello")) -> None:
        self.url = "about:blank"
        self.sent = False
        self.respond = True
        self.quota = False
        self.logged_out = False
        self.reject_inserts = 0
        self.polls = 0
        self.stream = stream
        self.never_settles = False
        self.goto_calls: list[str] = []
        self.closed = False
        self.composer = FakeComposer(self)
        self.turn = FakeTurn(self)
        self.keyboard = FakeKeyboard(self)

    def locator(self, selector: str) -> FakeLocator:
        return {
            "#composer": self.composer,
            "#assistant": self.turn,
            "#signin": FakeLocator(present=self.logged_out),
            "#quota": FakeLocator(present=self.quota),
            "#send": FakeLocator(present=False),
            "#stop": FakeLocator(present=False),
        }.get(selector, FakeLocator(present=False))

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_calls.append(url)
        self.url = url

    async def close(self) -> None:
        self.closed = True

    # --- text script ---------------------------------------------------------------

    def next_text(self) -> str:
        if not self.sent or not self.respond:
            return ""
        self.polls += 1
        if self.never_settles:
            return "x" * self.polls
        return self.stream[min(self.polls - 1, len(self.stream) - 1)]

    def peek_text(self) -> str:
        if not self.sent or not self.respond:
            return ""
        if self.never_settles:
            return "x" * max(self.polls, 1)
        return self.stream[min(max(self.polls - 1, 0), len(self.stream) - 1)]


# --- daemon fakes ----------------------------------------------------------------------


@dataclass
class FakeProvider:
    """Implements the Provider protocol without Chrome."""

    id: str = "fake"
    delay_s: float = 0.0
    error: Exception | None = None
    text: str = "answer"
    calls: list[str] = field(default_factory=list)
    disposed: bool = False
    gate: asyncio.Event | None = None

    async def health(self) -> Health:
        return Health(provider=self.id, reachable=True, logged_in=True)

    async def ask(self, req: Any) -> AskResult:
        self.calls.append(req.prompt)
        if self.gate is not None:
            await self.gate.wait()
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        return AskResult(
            provider=self.id,
            text_markdown=self.text,
            conversation_url=f"https://example.test/{self.id}",
        )

    async def dispose(self) -> None:
        self.disposed = True
