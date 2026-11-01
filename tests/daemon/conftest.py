"""Daemon fixtures: a fake provider, a TestClient, and auth headers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relay.daemon.app import create_app
from tests.fakes import FakeProvider

TOKEN = "test-token"


class FakeSurface(FakeProvider):
    """A provider that also supports the maintenance routes."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.home_opened = False

    async def open_home(self) -> str:
        self.home_opened = True
        return "https://example.test/login"

    async def doctor(self) -> dict[str, dict[str, Any]]:
        return {"composer": {"ok": True, "index": 0, "optional": False}}


@pytest.fixture
def provider() -> FakeSurface:
    return FakeSurface(id="chatgpt")


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(provider: FakeSurface, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        providers={"chatgpt": provider},
        token=TOKEN,
        db_path=tmp_path / "state.db",
    )
    with TestClient(app) as test_client:
        yield test_client
