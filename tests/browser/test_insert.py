"""Text insertion and submission.

``insert_text`` must work on ProseMirror, rich-textarea and plain contenteditable — and must raise
``SendFailed`` when the editor refuses the text, so "slow model" and "rejected input" never blur.
"""

from __future__ import annotations

from typing import Any

import pytest

from relay.browser import dom
from relay.errors import SendFailed
from tests.browser.stubs import StubKeyboard, StubLocator, StubPage


async def test_insert_uses_keyboard_insert_and_focuses_the_composer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dom, "_SETTLE_MS", 30)
    composer = StubLocator(text="")
    page = StubPage({}, StubKeyboard(composer))

    await dom.insert_text(page, composer, "hello")  # type: ignore[arg-type]

    assert page.keyboard.typed == ["hello"]
    assert composer.clicked == 1


async def test_insert_and_send_presses_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dom, "_SETTLE_MS", 30)
    composer = StubLocator(text="")
    page = StubPage({}, StubKeyboard(composer))

    await dom.insert_and_send(page, composer, "hi")  # type: ignore[arg-type]

    assert page.keyboard.pressed == ["Enter"]


async def test_empty_composer_after_insert_raises_send_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dom, "_SETTLE_MS", 30)
    composer = StubLocator(text="")
    page = StubPage({}, StubKeyboard(None))

    with pytest.raises(SendFailed):
        await dom.insert_text(page, composer, "hello")  # type: ignore[arg-type]


async def test_falls_back_to_execcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dom, "_SETTLE_MS", 30)

    class ExecCommandComposer(StubLocator):
        async def evaluate(self, script: str, arg: Any = None) -> Any:
            if "execCommand" in script:
                self.text = str(arg)
                return None
            return self.text

    composer = ExecCommandComposer(text="")
    page = StubPage({}, StubKeyboard(None))

    await dom.insert_text(page, composer, "fallback")  # type: ignore[arg-type]

    assert composer.text == "fallback"


async def test_composer_text_reads_the_element() -> None:
    assert await dom.composer_text(StubLocator(text="typed")) == "typed"  # type: ignore[arg-type]
