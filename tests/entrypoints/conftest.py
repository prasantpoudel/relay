"""A DaemonClient stand-in for entry-point tests. No socket, no daemon, no browser."""

from __future__ import annotations

from typing import Any


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.ask_payload: dict[str, Any] = {
            "status": "done",
            "result": {
                "provider": "chatgpt",
                "text_markdown": "the answer",
                "conversation_url": "https://chatgpt.com/c/1",
                "untrusted": True,
            },
        }
        self.status_payload: dict[str, Any] = {
            "providers": [
                {
                    "id": "chatgpt",
                    "logged_in": True,
                    "last_error": None,
                    "selectors": [{"name": "composer", "index": 0, "hits": 4}],
                }
            ],
            "queue_depth": {},
        }
        self.login_payload: dict[str, Any] = {
            "provider": "chatgpt",
            "url": "https://chatgpt.com/auth/login",
        }
        self.doctor_payload: dict[str, Any] = {
            "provider": "chatgpt",
            "selectors": {
                "composer": {"ok": True, "index": 0, "optional": False},
                "assistant_turn": {"ok": False, "index": None, "optional": True},
            },
        }
        self.result_payload: dict[str, Any] = self.ask_payload
        self.raise_on_ask: Exception | None = None

    def ensure_running(self, **kwargs: Any) -> None:
        self.calls.append(("ensure_running",))

    def ask(self, provider: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("ask", provider, prompt))
        if self.raise_on_ask is not None:
            raise self.raise_on_ask
        return self.ask_payload

    def wait_for_result(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("wait_for_result", task_id))
        return self.result_payload

    def status(self) -> dict[str, Any]:
        self.calls.append(("status",))
        return self.status_payload

    def login(self, provider: str) -> dict[str, Any]:
        self.calls.append(("login", provider))
        return self.login_payload

    def doctor(self, provider: str) -> dict[str, Any]:
        self.calls.append(("doctor", provider))
        return self.doctor_payload

    def close(self) -> None:
        self.calls.append(("close",))


__all__ = ["FakeClient"]
