"""HTTP client shared by the CLI and the MCP shim.

One place that knows the daemon's routes, the bearer header, and how to turn an error payload back
into a typed failure. Neither entry point talks to ``httpx`` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from relay.client import DaemonClient
from relay.errors import GenerationTimeout, ProviderUnavailable, RemoteFailure

TOKEN = "test-token"


class Recorder:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = responses or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.responses:
            value = self.responses[path]
            if callable(value):
                return value(request)
            return httpx.Response(200, json=value)
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"status": "done"})


def make_client(recorder: Recorder, **kwargs: Any) -> DaemonClient:
    return DaemonClient(
        token=TOKEN,
        transport=httpx.MockTransport(recorder.handler),
        **kwargs,
    )


def test_every_request_carries_the_bearer_token() -> None:
    recorder = Recorder()
    client = make_client(recorder)

    client.status()

    assert recorder.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_base_url_defaults_to_loopback() -> None:
    client = DaemonClient(token=TOKEN)

    assert client.base_url.startswith("http://127.0.0.1:")


def test_port_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_PORT", "9999")

    client = DaemonClient(token=TOKEN)

    assert client.base_url.endswith(":9999")


def test_health_is_true_on_200() -> None:
    assert make_client(Recorder()).health() is True


def test_health_is_false_when_the_daemon_is_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = DaemonClient(token=TOKEN, transport=httpx.MockTransport(refuse))

    assert client.health() is False


def test_ask_posts_the_request() -> None:
    recorder = Recorder()
    client = make_client(recorder)

    payload = client.ask("chatgpt", "hello", max_wait_s=5)

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/ask"
    assert b'"prompt":"hello"' in request.content
    assert payload["status"] == "done"


def test_an_error_payload_becomes_a_typed_failure() -> None:
    recorder = Recorder(
        {
            "/ask": lambda request: httpx.Response(
                429,
                json={
                    "status": "error",
                    "error": {
                        "code": "quota_exceeded",
                        "message": "limit reached",
                        "http_status": 429,
                    },
                },
            )
        }
    )
    client = make_client(recorder)

    with pytest.raises(RemoteFailure) as caught:
        client.ask("chatgpt", "hello")

    assert caught.value.code == "quota_exceeded"
    assert caught.value.http_status == 429
    assert "limit reached" in str(caught.value)


def test_unknown_task_surfaces_as_a_failure() -> None:
    recorder = Recorder({"/result/nope": lambda request: httpx.Response(404, json={"detail": "x"})})
    client = make_client(recorder)

    with pytest.raises(RemoteFailure):
        client.result("nope")


def test_status_login_and_doctor_hit_their_routes() -> None:
    recorder = Recorder(
        {
            "/status": {"providers": []},
            "/login/gemini": {"provider": "gemini", "url": "https://gemini.google.com"},
            "/doctor/gemini": {"provider": "gemini", "selectors": {}},
        }
    )
    client = make_client(recorder)

    client.status()
    client.login("gemini")
    client.doctor("gemini")

    assert [request.url.path for request in recorder.requests] == [
        "/status",
        "/login/gemini",
        "/doctor/gemini",
    ]


def test_wait_for_result_polls_until_done() -> None:
    calls = {"n": 0}

    def result(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"status": "pending", "task_id": "abc"})
        return httpx.Response(200, json={"status": "done", "result": {"text_markdown": "ok"}})

    client = make_client(Recorder({"/result/abc": result}))

    payload = client.wait_for_result("abc", timeout_s=1, interval_s=0.001)

    assert payload["status"] == "done"
    assert calls["n"] == 3


def test_wait_for_result_times_out_with_a_next_action() -> None:
    client = make_client(Recorder({"/result/abc": {"status": "pending", "task_id": "abc"}}))

    with pytest.raises(GenerationTimeout, match="bridge_result"):
        client.wait_for_result("abc", timeout_s=0.02, interval_s=0.005)


def test_ensure_running_spawns_once_and_waits_for_health() -> None:
    states = {"up": False}
    spawned: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if states["up"]:
            return httpx.Response(200, json={"ok": True})
        raise httpx.ConnectError("down", request=request)

    client = DaemonClient(token=TOKEN, transport=httpx.MockTransport(handler))

    def spawn() -> None:
        spawned.append(1)
        states["up"] = True

    client.ensure_running(timeout_s=1, spawn=spawn)

    assert spawned == [1]


def test_ensure_running_raises_when_the_daemon_never_comes_up() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    client = DaemonClient(token=TOKEN, transport=httpx.MockTransport(refuse))

    with pytest.raises(ProviderUnavailable, match="relay daemon"):
        client.ensure_running(timeout_s=0.05, spawn=lambda: None)


def test_token_file_is_created_when_none_is_given(tmp_path: Path) -> None:
    from relay.util import token as token_module

    monkeypatch_target = token_module.read_or_create_token
    token_module.read_or_create_token = lambda: "from-file"  # type: ignore[assignment]
    try:
        client = DaemonClient()
    finally:
        token_module.read_or_create_token = monkeypatch_target  # type: ignore[assignment]

    assert client.token == "from-file"
