"""Shared driver fixture: a real ``BrowserProvider`` on a fake page and a temp SQLite file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from relay.drivers.base import AskRequest, Selectors
from relay.drivers.browser_provider import BrowserProvider
from tests.fakes import FakePage


def test_selectors() -> Selectors:
    return Selectors(
        {
            "composer": ["#composer", "#composer-alt"],
            "assistant_turn": ["#assistant"],
            "send": ["#send"],
            "stop": ["#stop"],
            "quota_banner": ["#quota"],
            "logged_out": ["#signin"],
        }
    )


class TestProvider(BrowserProvider):
    """Fast timeouts so the suite stays under a second per behaviour."""

    id = "test"
    home_url = "https://example.test/"
    new_chat_url = "https://example.test/new"

    first_token_timeout_s = 0.2
    composer_timeout_ms = 40
    doctor_timeout_ms = 20
    insert_settle_ms = 20
    min_stable_s = 0.02
    poll_s = 0.01

    def __init__(self, fake_page: FakePage, db_path: Path) -> None:
        super().__init__(selectors=test_selectors(), state_path=db_path)
        self.fake_page = fake_page

    async def _ensure_page(self) -> Any:
        self._page = self.fake_page
        return self.fake_page


@pytest.fixture
def page() -> FakePage:
    return FakePage()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def provider(page: FakePage, db_path: Path) -> TestProvider:
    return TestProvider(page, db_path)


@pytest.fixture
def ask() -> Callable[..., AskRequest]:
    def make(prompt: str = "hi", **overrides: Any) -> AskRequest:
        payload: dict[str, Any] = {"provider": "test", "prompt": prompt}
        payload.update(overrides)
        return AskRequest(**payload)

    return make
