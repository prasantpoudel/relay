"""CLI behaviour, with a fake daemon client.

The CLI formats and exits; it does not transport. Every failure must print a next action and exit
non-zero, never a traceback.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from relay import cli
from relay.errors import GenerationTimeout, RemoteFailure
from tests.entrypoints.conftest import FakeClient

runner = CliRunner()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(cli, "get_client", lambda: fake)
    return fake


def invoke(*args: str) -> object:
    return runner.invoke(cli.app, list(args))


# --- version ---------------------------------------------------------------------------


def test_version_prints_the_package_version() -> None:
    from relay import __version__

    result = invoke("version")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert __version__ in result.stdout  # type: ignore[attr-defined]


# --- ask -------------------------------------------------------------------------------


def test_ask_prints_the_answer_and_the_untrusted_banner(client: FakeClient) -> None:
    result = invoke("ask", "chatgpt", "what is 2+2")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "the answer" in result.stdout  # type: ignore[attr-defined]
    assert "untrusted" in result.stdout.lower()  # type: ignore[attr-defined]
    assert client.calls[0] == ("ensure_running",)


def test_ask_forwards_the_prompt(client: FakeClient) -> None:
    invoke("ask", "chatgpt", "say OK")

    assert ("ask", "chatgpt", "say OK") in client.calls


def test_pending_answer_without_follow_prints_the_task_id(client: FakeClient) -> None:
    client.ask_payload = {"status": "pending", "task_id": "abc123"}

    result = invoke("ask", "chatgpt", "slow question", "--no-follow")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "abc123" in result.stdout  # type: ignore[attr-defined]
    assert "bridge_result" in result.stdout  # type: ignore[attr-defined]


def test_pending_answer_with_follow_polls_until_done(client: FakeClient) -> None:
    client.ask_payload = {"status": "pending", "task_id": "abc123"}

    result = invoke("ask", "chatgpt", "slow question")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert ("wait_for_result", "abc123") in client.calls
    assert "the answer" in result.stdout  # type: ignore[attr-defined]


def test_a_typed_failure_exits_non_zero_with_the_message(client: FakeClient) -> None:
    client.raise_on_ask = RemoteFailure("quota_exceeded", "limit reached until 18:00", 429)

    result = invoke("ask", "chatgpt", "hi")

    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert "limit reached until 18:00" in result.stdout  # type: ignore[attr-defined]


def test_a_generation_timeout_names_the_recovery_command(client: FakeClient) -> None:
    client.raise_on_ask = GenerationTimeout("still running; use bridge_result with task_id=abc")

    result = invoke("ask", "chatgpt", "hi")

    assert result.exit_code == 1  # type: ignore[attr-defined]
    assert "bridge_result" in result.stdout  # type: ignore[attr-defined]


# --- status ----------------------------------------------------------------------------


def test_status_shows_login_state_and_drift(client: FakeClient) -> None:
    result = invoke("status")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "chatgpt" in result.stdout  # type: ignore[attr-defined]
    assert "logged in" in result.stdout.lower()  # type: ignore[attr-defined]


def test_status_flags_a_selector_that_resolved_at_a_fallback_index(client: FakeClient) -> None:
    client.status_payload["providers"][0]["selectors"] = [
        {"name": "composer", "index": 2, "hits": 9}
    ]

    result = invoke("status")

    assert "drift" in result.stdout.lower()  # type: ignore[attr-defined]
    assert "composer" in result.stdout  # type: ignore[attr-defined]


# --- login and doctor ------------------------------------------------------------------


def test_login_prints_the_url_and_the_next_step(client: FakeClient) -> None:
    result = invoke("login", "chatgpt")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "https://chatgpt.com/auth/login" in result.stdout  # type: ignore[attr-defined]


def test_doctor_lists_each_selector_with_its_index(client: FakeClient) -> None:
    result = invoke("doctor", "chatgpt")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "composer" in result.stdout  # type: ignore[attr-defined]
    assert "index 0" in result.stdout  # type: ignore[attr-defined]


def test_doctor_exits_non_zero_when_a_required_selector_is_missing(client: FakeClient) -> None:
    client.doctor_payload["selectors"]["composer"] = {"ok": False, "index": None, "optional": False}

    result = invoke("doctor", "chatgpt")

    assert result.exit_code == 1  # type: ignore[attr-defined]


# --- process control -------------------------------------------------------------------


def test_launch_starts_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    async def fake_ensure_running() -> str:
        started.append("up")
        return "http://127.0.0.1:9222"

    monkeypatch.setattr(cli.chrome, "ensure_running", fake_ensure_running)

    result = invoke("launch")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert started == ["up"]


def test_daemon_background_asks_the_client_to_start_it(client: FakeClient) -> None:
    result = invoke("daemon", "--background")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert ("ensure_running",) in client.calls


def test_daemon_foreground_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_run(app: object, *, host: str, port: int, **kwargs: object) -> None:
        calls.append((host, port))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = invoke("daemon", "--port", "8989")

    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert calls == [("127.0.0.1", 8989)]
