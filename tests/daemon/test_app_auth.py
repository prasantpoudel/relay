"""Authentication boundary: loopback is not a permission system."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_needs_no_token(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_reports_a_version(client: TestClient) -> None:
    assert client.get("/health").json()["version"]


def test_status_rejects_a_missing_token(client: TestClient) -> None:
    assert client.get("/status").status_code == 401


def test_a_wrong_token_is_rejected(client: TestClient) -> None:
    response = client.get("/status", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


def test_a_malformed_header_is_rejected(client: TestClient) -> None:
    response = client.get("/status", headers={"Authorization": "test-token"})

    assert response.status_code == 401


def test_the_right_token_is_accepted(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/status", headers=auth).status_code == 200
