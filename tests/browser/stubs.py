"""Browser stubs: enough of Playwright to exercise ``browser/`` without a process."""

from __future__ import annotations

from typing import Any


class StubLocator:
    def __init__(self, *, visible: bool = True, present: bool = True, text: str = "") -> None:
        self.visible = visible
        self.present = present
        self.text = text
        self.clicked = 0

    @property
    def first(self) -> StubLocator:
        return self

    async def count(self) -> int:
        return 1 if self.present else 0

    async def is_visible(self) -> bool:
        return self.visible

    async def click(self) -> None:
        self.clicked += 1

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "execCommand" in script:
            return None
        return self.text


class StubKeyboard:
    def __init__(self, composer: StubLocator | None = None) -> None:
        self.composer = composer
        self.typed: list[str] = []
        self.pressed: list[str] = []

    async def insert_text(self, text: str) -> None:
        self.typed.append(text)
        if self.composer is not None:
            self.composer.text = text

    async def press(self, key: str) -> None:
        self.pressed.append(key)


class StubPage:
    def __init__(
        self, mapping: dict[str, StubLocator], keyboard: StubKeyboard | None = None
    ) -> None:
        self.mapping = mapping
        self.keyboard = keyboard or StubKeyboard()

    def locator(self, selector: str) -> StubLocator:
        return self.mapping.get(selector, StubLocator(present=False))


__all__ = ["StubKeyboard", "StubLocator", "StubPage"]
