"""One implementation of the ask flow. Concrete drivers supply only what differs.

Everything provider-independent lives here: navigation, composer resolution, insertion, the
first-token guard, stability polling, extraction, quota detection, and drift recording.

The hooks a driver may override are listed under "Hooks" at the bottom. If a driver needs more than
that, the seam is wrong — fix the seam, not the driver.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..browser import chrome, dom
from ..errors import NotLoggedIn, QuotaExceeded, RelayError, SendFailed
from ..util import markdown as md
from ..util import state
from ..util.log import get_logger
from .base import AskRequest, AskResult, Health, Selectors

log = get_logger("drivers")

# Selectors that only exist once a conversation has started, so doctor reports them as
# "not applicable" on an empty new chat instead of implying the UI moved.
OPTIONAL_SELECTORS = frozenset({"assistant_turn", "stop", "quota_banner"})


class BrowserProvider:
    """Drives one provider's web UI through an already-logged-in Chrome profile."""

    id = "browser"
    home_url = ""
    new_chat_url = ""
    # CSS selector for the answer body inside the assistant turn, when the turn element also
    # contains chrome the generic extractor cannot strip.
    content_selector: str | None = None

    selectors_file: Path | None = None

    first_token_timeout_s = 30.0
    composer_timeout_ms = 15_000.0
    insert_settle_ms = 2_000.0
    health_timeout_ms = 8_000.0
    doctor_timeout_ms = 1_500.0
    min_stable_s = 1.2
    poll_s = 0.4
    max_send_attempts = 2

    def __init__(
        self,
        *,
        selectors: Selectors | None = None,
        selectors_file: Path | None = None,
        state_path: Path | None = None,
    ) -> None:
        source = selectors_file or self.selectors_file
        if selectors is None:
            if source is None:
                raise ValueError(f"{type(self).__name__} has no selectors file configured")
            selectors = Selectors.load(source)
        self.selectors = selectors
        self._state_path = state_path
        self._page: Page | None = None

    # --- lifecycle ---------------------------------------------------------------------

    async def _ensure_page(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page

        browser = await chrome.connect()
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(15_000)
        page.set_default_navigation_timeout(45_000)
        self._page = page
        return page

    async def dispose(self) -> None:
        page, self._page = self._page, None
        if page is None:
            return
        try:
            await page.close()
        except PlaywrightError:
            log.debug("%s: page close failed", self.id, exc_info=True)

    async def __aenter__(self) -> BrowserProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.dispose()

    # --- public surface ----------------------------------------------------------------

    async def ask(self, req: AskRequest) -> AskResult:
        started = time.monotonic()
        page = await self._ensure_page()

        await self._open(page, req)
        await self._assert_logged_in(page)

        composer, index = await dom.resolve(
            page,
            self.selectors.get("composer", provider=self.id),
            provider=self.id,
            name="composer",
            timeout_ms=self.composer_timeout_ms,
        )
        self._record("composer", index)

        before_count = await self._turn_count(page)
        before_text = await self._last_turn_text(page)

        await self._send_with_retry(page, composer, req, before_count, before_text)
        await self._check_quota(page)

        text, timed_out = await dom.stable_text(
            lambda: self._last_turn_text(page),
            min_stable_s=self.min_stable_s,
            poll_s=self.poll_s,
            timeout_s=req.settle_timeout_s,
        )

        if not text.strip():
            await self._check_quota(page)

        html = await self._last_turn_html(page)
        markdown = md.html_to_markdown(html) or text

        url = await self._conversation_url(page)
        self._remember_conversation(url)

        return AskResult(
            provider=self.id,
            text_markdown=markdown,
            conversation_url=url,
            model=self._model_name(page),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            truncated=timed_out,
            untrusted=True,
        )

    async def health(self) -> Health:
        """Probe reachability and login state without sending a prompt."""
        try:
            page = await self._ensure_page()
            await self._goto(page, self.home_url)

            if await self._logged_out(page):
                self._set_state(logged_in=False, error="signed out")
                return Health(
                    provider=self.id,
                    reachable=True,
                    logged_in=False,
                    detail=f"signed out — run `relay login {self.id}`",
                )

            _, index = await dom.resolve(
                page,
                self.selectors.get("composer", provider=self.id),
                provider=self.id,
                name="composer",
                timeout_ms=self.health_timeout_ms,
            )
            self._record("composer", index)
            self._set_state(logged_in=True)
            return Health(
                provider=self.id,
                reachable=True,
                logged_in=True,
                detail=f"composer at selector index {index}",
            )
        except RelayError as exc:
            self._set_state(logged_in=False, error=str(exc))
            return Health(provider=self.id, reachable=False, logged_in=None, detail=str(exc))
        except Exception as exc:
            log.exception("%s: health check failed", self.id)
            self._set_state(logged_in=False, error=str(exc))
            return Health(provider=self.id, reachable=False, logged_in=None, detail=str(exc))

    async def doctor(self) -> dict[str, dict[str, Any]]:
        """Resolve every configured selector and report the index that matched.

        This is the maintenance tool: a selector that used to hit index 0 and now hits index 2 is
        the earliest possible warning that the provider changed its DOM.
        """
        page = await self._ensure_page()
        await self._goto(page, self.home_url)

        report: dict[str, dict[str, Any]] = {}
        for name in self.selectors.names():
            optional = name in OPTIONAL_SELECTORS
            try:
                _, index = await dom.resolve(
                    page,
                    self.selectors.get(name, provider=self.id),
                    provider=self.id,
                    name=name,
                    timeout_ms=self.doctor_timeout_ms,
                )
            except RelayError:
                report[name] = {"ok": False, "index": None, "optional": optional}
                continue

            self._record(name, index)
            report[name] = {"ok": True, "index": index, "optional": optional}

        return report

    async def open_home(self) -> str:
        """Open the provider's home page so the user can sign in. Returns the URL."""
        page = await self._ensure_page()
        await self._goto(page, self.home_url)
        return page.url

    # --- flow --------------------------------------------------------------------------

    async def _send_with_retry(
        self,
        page: Page,
        composer: Locator,
        req: AskRequest,
        before_count: int,
        before_text: str,
    ) -> None:
        for attempt in range(1, self.max_send_attempts + 1):
            try:
                await dom.insert_and_send(
                    page, composer, req.prompt, settle_ms=self.insert_settle_ms
                )
            except SendFailed:
                if attempt == self.max_send_attempts:
                    raise
                log.warning("%s: insert rejected, retrying once", self.id)
                await dom.clear_composer(page, composer)
                continue

            if await self._await_first_token(page, before_count, before_text):
                return

            # A quota dialog can replace the answer entirely, so name it before blaming the send.
            await self._check_quota(page)

            if attempt == self.max_send_attempts:
                raise SendFailed(
                    f"{self.id}: no assistant turn appeared within "
                    f"{self.first_token_timeout_s:.0f}s of sending. The composer accepted the text "
                    f"but the message was not submitted — run `relay doctor {self.id}`."
                )

            log.warning("%s: no first token, retrying once", self.id)
            await dom.clear_composer(page, composer)

    async def _await_first_token(
        self, page: Page, before_count: int, before_text: str, *, timeout_s: float | None = None
    ) -> bool:
        deadline = time.monotonic() + (timeout_s or self.first_token_timeout_s)
        while time.monotonic() < deadline:
            if await self._turn_count(page) > before_count:
                return True
            if await self._last_turn_text(page) != before_text:
                return True
            await asyncio.sleep(0.1)
        return False

    async def _open(self, page: Page, req: AskRequest) -> None:
        url = self.new_chat_url if req.new_chat else (req.conversation_url or self.new_chat_url)
        await self._goto(page, url)

    async def _goto(self, page: Page, url: str) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            # A slow page is not a failure by itself; the selector resolve is the real gate.
            log.warning("%s: navigation to %s timed out; continuing", self.id, url)

    # --- hooks -------------------------------------------------------------------------

    def _turn_chain(self) -> Sequence[str]:
        return self.selectors.get("assistant_turn", provider=self.id)

    async def _turn_locator(self, page: Page) -> Locator:
        chain = self._turn_chain()
        for selector in chain:
            locator = page.locator(selector)
            try:
                if await locator.count():
                    return locator
            except PlaywrightError:
                continue
        return page.locator(chain[0])

    async def _turn_count(self, page: Page) -> int:
        try:
            return await (await self._turn_locator(page)).count()
        except PlaywrightError:
            return 0

    async def _last_turn_text(self, page: Page) -> str:
        try:
            return await (await self._turn_locator(page)).last.inner_text()
        except PlaywrightError:
            return ""

    async def _last_turn_html(self, page: Page) -> str:
        try:
            turn = (await self._turn_locator(page)).last
            if self.content_selector:
                inner = turn.locator(self.content_selector)
                if await inner.count():
                    return await inner.last.inner_html()
            return await turn.inner_html()
        except PlaywrightError:
            return ""

    async def _check_quota(self, page: Page) -> None:
        for selector in self.selectors.optional("quota_banner"):
            if await self._visible(page, selector):
                raise QuotaExceeded(
                    f"{self.id} is rate-limited on the free tier. Wait for the limit to reset, "
                    f"then retry."
                )

    async def _conversation_url(self, page: Page) -> str:
        return page.url

    def _model_name(self, page: Page) -> str | None:
        return None

    # --- guards and telemetry ----------------------------------------------------------

    async def _assert_logged_in(self, page: Page) -> None:
        if await self._logged_out(page):
            raise NotLoggedIn(
                f"{self.id} is signed out. Run `relay login {self.id}`, sign in in the window "
                f"that opens, then retry."
            )

    async def _logged_out(self, page: Page) -> bool:
        for selector in self.selectors.optional("logged_out"):
            if await self._visible(page, selector):
                return True
        return False

    async def _visible(self, page: Page, selector: str) -> bool:
        try:
            locator = page.locator(selector).first
            return await locator.count() > 0 and await locator.is_visible()
        except PlaywrightError:
            return False

    def _record(self, name: str, index: int) -> None:
        try:
            with state.session(self._state_path) as conn:
                state.record_selector_hit(conn, self.id, name, index)
        except (sqlite3.Error, OSError):
            log.debug("%s: could not record selector hit", self.id, exc_info=True)

    def _remember_conversation(self, url: str) -> None:
        if not url or url == "about:blank":
            return
        try:
            with state.session(self._state_path) as conn:
                state.put_conversation(conn, self.id, url)
        except (sqlite3.Error, OSError):
            log.debug("%s: could not remember conversation", self.id, exc_info=True)

    def _set_state(self, *, logged_in: bool, error: str | None = None) -> None:
        try:
            with state.session(self._state_path) as conn:
                state.set_provider_state(conn, self.id, logged_in=logged_in, error=error)
        except (sqlite3.Error, OSError):
            log.debug("%s: could not record provider state", self.id, exc_info=True)


__all__ = ["OPTIONAL_SELECTORS", "BrowserProvider"]
