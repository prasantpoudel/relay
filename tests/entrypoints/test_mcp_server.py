"""MCP shim: five tools, no stdout writes, no browser imports.

The contract these tests defend is small and load-bearing: stdout is the JSON-RPC channel, the tool
surface is fixed, and everything returned is labelled untrusted.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any

import pytest

from relay import mcp_server
from relay.errors import RemoteFailure
from tests.entrypoints.conftest import FakeClient

TOOL_NAMES = {"bridge_ask", "bridge_result", "bridge_status", "bridge_login", "bridge_doctor"}


def tools() -> list[Any]:
    return asyncio.run(mcp_server.server.list_tools())


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(mcp_server, "get_client", lambda: client)
    return client


# --- the stdout ban --------------------------------------------------------------------


def test_the_module_never_calls_print() -> None:
    source = inspect.getsource(mcp_server)

    assert not re.search(r"(^|\s)print\s*\(", source, re.MULTILINE)
    assert "sys.stdout.write" not in source


def test_the_module_never_imports_a_browser_or_a_web_framework() -> None:
    source = inspect.getsource(mcp_server)

    assert "playwright" not in source
    assert "fastapi" not in source


# --- tool surface ----------------------------------------------------------------------


def test_exactly_five_tools_are_registered() -> None:
    names = {tool.name for tool in tools()}

    assert names == TOOL_NAMES


def test_no_general_purpose_browser_tool_exists() -> None:
    names = {tool.name for tool in tools()}

    assert not names & {"navigate", "click", "eval", "screenshot", "fetch"}


def test_ask_description_carries_the_untrusted_contract() -> None:
    tool = next(t for t in tools() if t.name == "bridge_ask")

    assert "untrusted" in (tool.description or "").lower()
    assert "not instructions" in (tool.description or "").lower()


# --- behaviour -------------------------------------------------------------------------


def test_bridge_ask_returns_the_answer_with_a_banner(fake: FakeClient) -> None:
    text = mcp_server.bridge_ask("chatgpt", "hi")

    assert "the answer" in text
    assert "untrusted" in text.lower()
    assert fake.calls[0] == ("ensure_running",)


def test_bridge_ask_pending_returns_the_task_id(fake: FakeClient) -> None:
    fake.ask_payload = {"status": "pending", "task_id": "abc123"}

    text = mcp_server.bridge_ask("chatgpt", "slow")

    assert "abc123" in text
    assert "bridge_result" in text


def test_bridge_result_fetches_a_finished_task(fake: FakeClient) -> None:
    text = mcp_server.bridge_result("abc123")

    assert ("wait_for_result", "abc123") in fake.calls
    assert "the answer" in text


def test_bridge_result_reports_an_error_without_raising(fake: FakeClient) -> None:
    fake.result_payload = {
        "status": "error",
        "error": {"code": "quota_exceeded", "message": "limit reached", "http_status": 429},
    }

    text = mcp_server.bridge_result("abc123")

    assert "quota_exceeded" in text
    assert "limit reached" in text


def test_bridge_status_lists_providers(fake: FakeClient) -> None:
    text = mcp_server.bridge_status()

    assert "chatgpt" in text
    assert "logged in" in text.lower()


def test_bridge_login_returns_the_url(fake: FakeClient) -> None:
    text = mcp_server.bridge_login("chatgpt")

    assert "https://chatgpt.com/auth/login" in text


def test_bridge_doctor_marks_missing_optional_selectors_as_skipped(fake: FakeClient) -> None:
    text = mcp_server.bridge_doctor("chatgpt")

    assert "composer" in text
    assert "skipped" in text.lower()


def test_daemon_failures_are_reported_as_text_not_exceptions(fake: FakeClient) -> None:
    fake.raise_on_ask = RemoteFailure("provider_unavailable", "run `relay launch`", 503)

    text = mcp_server.bridge_ask("chatgpt", "hi")

    assert "provider_unavailable" in text
    assert "relay launch" in text
