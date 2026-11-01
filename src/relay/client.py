"""HTTP client for the daemon, shared by the CLI and the MCP shim.

One place knows the routes, the bearer header, and how to turn an error payload back into a typed
failure. Entry points stay thin: they format, they do not transport.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from .errors import GenerationTimeout, ProviderUnavailable, RemoteFailure
from .util import token as token_store
from .util.log import RELAY_HOME, get_logger

log = get_logger("client")

DEFAULT_PORT = 8787
# Larger than the daemon's default max_wait_s: the daemon decides when to answer "pending", so the
# client should not be the one that gives up first.
DEFAULT_TIMEOUT_S = 900.0


def default_base_url() -> str:
    port = int(os.environ.get("RELAY_PORT", str(DEFAULT_PORT)))
    return f"http://127.0.0.1:{port}"


class DaemonClient:
    """Typed wrapper over the daemon's HTTP surface."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.base_url = base_url or default_base_url()
        self.token = token or token_store.read_or_create_token()
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            transport=transport,
            timeout=timeout_s,
        )

    # --- lifecycle ---------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DaemonClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def health(self) -> bool:
        """True when a daemon answers ``/health``. Never raises."""
        try:
            return self._client.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    def ensure_running(self, *, timeout_s: float = 20.0, spawn: Any = None) -> None:
        """Start the daemon if it is not up, then wait for ``/health``."""
        if self.health():
            return

        starter = spawn or self._spawn
        starter()

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.health():
                return
            time.sleep(0.1)

        raise ProviderUnavailable(
            f"relay daemon did not answer at {self.base_url} within {timeout_s:.0f}s. "
            "Start it in the foreground with `relay daemon` to see the error."
        )

    def _spawn(self) -> None:
        log_dir = RELAY_HOME / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log.info("starting relay daemon on %s", self.base_url)
        with (log_dir / "daemon.log").open("ab") as sink:
            subprocess.Popen(
                [sys.executable, "-m", "relay.daemon"],
                stdout=sink,
                stderr=sink,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

    # --- routes ------------------------------------------------------------------------

    def ask(
        self,
        provider: str,
        prompt: str,
        *,
        new_chat: bool = True,
        conversation_url: str | None = None,
        max_wait_s: float = 120.0,
        settle_timeout_s: float = 600.0,
        model: str | None = None,
        attachments: list[Path] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "provider": provider,
            "prompt": prompt,
            "new_chat": new_chat,
            "max_wait_s": max_wait_s,
            "settle_timeout_s": settle_timeout_s,
        }
        if conversation_url:
            body["conversation_url"] = conversation_url
        if model:
            body["model"] = model
        if attachments:
            body["attachments"] = [str(path) for path in attachments]

        return self._decode(self._client.post("/ask", json=body))

    def result(self, task_id: str) -> dict[str, Any]:
        return self._decode(self._client.get(f"/result/{task_id}"))

    def status(self) -> dict[str, Any]:
        return self._decode(self._client.get("/status"))

    def login(self, provider: str) -> dict[str, Any]:
        return self._decode(self._client.post(f"/login/{provider}"))

    def doctor(self, provider: str) -> dict[str, Any]:
        return self._decode(self._client.get(f"/doctor/{provider}"))

    def wait_for_result(
        self, task_id: str, *, timeout_s: float = 600.0, interval_s: float = 2.0
    ) -> dict[str, Any]:
        """Poll until a pending task settles. Used by the CLI's ``--follow`` mode."""
        deadline = time.monotonic() + timeout_s
        while True:
            payload = self.result(task_id)
            if payload.get("status") != "pending":
                return payload
            if time.monotonic() >= deadline:
                raise GenerationTimeout(
                    f"task {task_id} is still running after {timeout_s:.0f}s. "
                    f"Call `bridge_result` with task_id='{task_id}' to collect it later."
                )
            time.sleep(interval_s)

    # --- errors ------------------------------------------------------------------------

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = response.json()
        except ValueError:
            payload = {}

        if response.status_code < 400:
            return payload

        error = payload.get("error") or {}
        message = (
            error.get("message")
            or payload.get("detail")
            or response.text
            or f"HTTP {response.status_code}"
        )
        raise RemoteFailure(
            str(error.get("code", "http_error")),
            str(message),
            int(error.get("http_status", response.status_code)),
        )


__all__ = ["DEFAULT_PORT", "DaemonClient", "default_base_url"]
