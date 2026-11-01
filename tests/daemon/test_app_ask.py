"""The ask route: synchronous when it can be, a task id when it cannot."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from relay.errors import QuotaExceeded
from tests.daemon.conftest import FakeSurface


def test_returns_the_answer_and_marks_it_untrusted(
    client: TestClient, auth: dict[str, str]
) -> None:
    response = client.post("/ask", json={"provider": "chatgpt", "prompt": "hi"}, headers=auth)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "done"
    assert payload["result"]["text_markdown"] == "answer"
    assert payload["result"]["untrusted"] is True
    assert payload["result"]["conversation_url"] == "https://example.test/chatgpt"


def test_the_prompt_reaches_the_driver(
    client: TestClient, provider: FakeSurface, auth: dict[str, str]
) -> None:
    client.post("/ask", json={"provider": "chatgpt", "prompt": "say OK"}, headers=auth)

    assert provider.calls == ["say OK"]


def test_a_typed_failure_keeps_its_http_status(
    client: TestClient, provider: FakeSurface, auth: dict[str, str]
) -> None:
    provider.error = QuotaExceeded("limit reached")

    response = client.post("/ask", json={"provider": "chatgpt", "prompt": "hi"}, headers=auth)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"


def test_unknown_provider_names_the_known_ones(client: TestClient, auth: dict[str, str]) -> None:
    response = client.post("/ask", json={"provider": "gpt-4", "prompt": "hi"}, headers=auth)

    assert response.status_code == 503
    assert "chatgpt" in response.text


def test_slow_ask_returns_a_task_id_instead_of_hanging(
    client: TestClient, provider: FakeSurface, auth: dict[str, str]
) -> None:
    provider.delay_s = 0.3

    response = client.post(
        "/ask",
        json={"provider": "chatgpt", "prompt": "hi", "max_wait_s": 0.01},
        headers=auth,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    task_id = payload["task_id"]

    polled: dict[str, Any] = {}
    for _ in range(100):
        polled = client.get(f"/result/{task_id}", headers=auth).json()
        if polled["status"] == "done":
            break
        time.sleep(0.02)

    assert polled["status"] == "done"
    assert polled["result"]["text_markdown"] == "answer"


def test_result_for_an_unknown_task_is_404(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/result/nope", headers=auth).status_code == 404
