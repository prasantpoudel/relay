"""Status, login, doctor, and shutdown."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from relay.daemon.app import create_app
from tests.daemon.conftest import TOKEN, FakeSurface


def test_status_lists_providers_and_queue_depth(client: TestClient, auth: dict[str, str]) -> None:
    payload = client.get("/status", headers=auth).json()

    ids = [entry["id"] for entry in payload["providers"]]
    assert ids == ["chatgpt"]
    assert payload["queue_depth"] == {}


def test_login_opens_the_provider_home(
    client: TestClient, provider: FakeSurface, auth: dict[str, str]
) -> None:
    response = client.post("/login/chatgpt", headers=auth)

    assert response.status_code == 200
    assert response.json()["url"] == "https://example.test/login"
    assert provider.home_opened is True


def test_login_for_an_unknown_provider_is_404(client: TestClient, auth: dict[str, str]) -> None:
    assert client.post("/login/nope", headers=auth).status_code == 404


def test_doctor_reports_selector_health(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get("/doctor/chatgpt", headers=auth)

    assert response.status_code == 200
    assert response.json()["selectors"]["composer"]["ok"] is True


def test_doctor_for_an_unknown_provider_is_404(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/doctor/nope", headers=auth).status_code == 404


def test_shutdown_disposes_every_provider(provider: FakeSurface, tmp_path: Path) -> None:
    app = create_app(providers={"chatgpt": provider}, token=TOKEN, db_path=tmp_path / "state.db")

    with TestClient(app):
        pass

    assert provider.disposed is True
