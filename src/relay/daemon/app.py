"""FastAPI daemon: auth, task lifecycle, per-provider serialisation.

Boundaries this module defends:

- Every route except ``/health`` needs the bearer token, compared in constant time.
- A failed generation is a task state with an HTTP status, never an unhandled exception.
- ``/ask`` blocks for at most ``max_wait_s``, then returns a task id so long generations survive
  hosts that time out.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..drivers import build_providers
from ..drivers.base import AskRequest, Provider
from ..errors import ProviderUnavailable, RelayError
from ..util import state
from ..util.log import get_logger
from ..util.token import read_or_create_token
from .queue import ProviderQueues
from .tasks import TaskRecord, TaskRegistry

log = get_logger("daemon")


class AskModel(BaseModel):
    provider: str
    prompt: str
    new_chat: bool = True
    conversation_url: str | None = None
    model: str | None = None
    attachments: list[str] = Field(default_factory=list)
    max_wait_s: float = 120.0
    settle_timeout_s: float = 600.0


def create_app(
    *,
    providers: Mapping[str, Provider] | None = None,
    token: str | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    registry: Mapping[str, Provider] = providers if providers is not None else build_providers()
    expected_token = token or read_or_create_token()
    queues = ProviderQueues()
    tasks = TaskRegistry(db_path=db_path)
    background: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("daemon ready: %s", ", ".join(sorted(registry)) or "no providers")
        yield
        for provider in registry.values():
            with contextlib.suppress(Exception):
                await provider.dispose()

    app = FastAPI(title="relay", version=__version__, lifespan=lifespan, docs_url=None)
    app.state.providers = registry
    app.state.tasks = tasks
    app.state.queues = queues

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not hmac.compare_digest(authorization[len("Bearer ") :], expected_token):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    auth = Depends(require_token)

    @app.exception_handler(RelayError)
    async def relay_error_handler(_: Request, exc: RelayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "status": "error",
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "http_status": exc.http_status,
                },
            },
        )

    def lookup(provider_id: str) -> Provider:
        provider = registry.get(provider_id)
        if provider is None:
            raise ProviderUnavailable(
                f"unknown provider '{provider_id}'. Known providers: "
                f"{', '.join(sorted(registry)) or 'none configured'}."
            )
        return provider

    def spawn(coro: Any) -> None:
        task: asyncio.Task[None] = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    async def run(task: TaskRecord, provider: Provider, request: AskRequest) -> None:
        async with queues.slot(provider.id):
            tasks.running(task.id)
            try:
                result = await provider.ask(request)
            except Exception as exc:
                tasks.fail(task.id, exc)
            else:
                tasks.complete(task.id, result)

    def respond(task: TaskRecord) -> Any:
        payload = task.to_dict()
        if task.status == "error" and task.error is not None:
            status = task.error.get("http_status", 500)
            return JSONResponse(status_code=int(status), content=payload)
        return payload

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.post("/ask")
    async def ask(payload: AskModel, _: None = auth) -> Any:
        provider = lookup(payload.provider)
        task = tasks.create(provider.id)

        request = AskRequest(
            provider=provider.id,
            prompt=payload.prompt,
            new_chat=payload.new_chat,
            conversation_url=payload.conversation_url,
            model=payload.model,
            attachments=[Path(path) for path in payload.attachments],
            max_wait_s=payload.max_wait_s,
            settle_timeout_s=payload.settle_timeout_s,
        )
        spawn(run(task, provider, request))

        try:
            await task.wait(payload.max_wait_s)
        except TimeoutError:
            return {"status": "pending", "task_id": task.id}

        return respond(task)

    @app.get("/result/{task_id}")
    async def result(task_id: str, _: None = auth) -> Any:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"unknown task '{task_id}'")
        return respond(task)

    @app.get("/status")
    async def status(_: None = auth) -> dict[str, Any]:
        provider_rows: dict[str, dict[str, Any]] = {}
        hits: list[dict[str, Any]] = []

        with state.session(db_path) as conn:
            for row in conn.execute("SELECT * FROM providers"):
                provider_rows[row["id"]] = dict(row)
            for row in conn.execute(
                "SELECT provider, name, idx, hits FROM selector_hits ORDER BY provider, name, idx"
            ):
                hits.append(dict(row))

        entries: list[dict[str, Any]] = []
        for provider_id in sorted(registry):
            row = provider_rows.get(provider_id)
            entries.append(
                {
                    "id": provider_id,
                    "logged_in": bool(row["logged_in"]) if row else None,
                    "last_checked": row["last_checked"] if row else None,
                    "last_error": row["last_error"] if row else None,
                    "selectors": [
                        {"name": hit["name"], "index": hit["idx"], "hits": hit["hits"]}
                        for hit in hits
                        if hit["provider"] == provider_id
                    ],
                }
            )

        return {
            "providers": entries,
            "queue_depth": {
                provider_id: queues.depth(provider_id)
                for provider_id in registry
                if queues.depth(provider_id)
            },
        }

    @app.post("/login/{provider_id}")
    async def login(provider_id: str, _: None = auth) -> dict[str, Any]:
        provider = registry.get(provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{provider_id}'")

        opener = getattr(provider, "open_home", None)
        if opener is None:
            raise HTTPException(
                status_code=501, detail=f"{provider_id} does not support opening a login page"
            )

        url: str = await opener()
        return {"provider": provider_id, "url": url}

    @app.get("/doctor/{provider_id}")
    async def doctor(provider_id: str, _: None = auth) -> dict[str, Any]:
        provider = registry.get(provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{provider_id}'")

        check = getattr(provider, "doctor", None)
        if check is None:
            raise HTTPException(
                status_code=501, detail=f"{provider_id} does not implement selector checks"
            )

        selectors: dict[str, Any] = await check()
        return {"provider": provider_id, "selectors": selectors}

    return app


__all__ = ["AskModel", "create_app"]
