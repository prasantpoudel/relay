"""Chrome process and CDP attachment.

Nothing above this module knows that Chrome exists. It owns exactly two things: the browser process
and the Playwright handle to it.

Why a dedicated profile is mandatory: Chrome 136+ ignores ``--remote-debugging-port`` when the
user-data-dir is the real default profile. There is no flag to work around it. ``~/.relay/chrome``
is therefore the single source of truth for login state, and the user signs in there once.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from playwright.async_api import Browser, Page, Playwright, async_playwright

from ..errors import ProviderUnavailable
from ..util.log import RELAY_HOME, get_logger

log = get_logger("chrome")

CDP_PORT = int(os.environ.get("RELAY_CDP_PORT", "9222"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
PROFILE_DIR = RELAY_HOME / "chrome"
LOG_DIR = RELAY_HOME / "logs"

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

# Anything here would show the "restore session" bubble or a first-run tab, which races the driver.
LAUNCH_FLAGS = (
    f"--remote-debugging-port={CDP_PORT}",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
)

_playwright: Playwright | None = None
_browser: Browser | None = None
_process: subprocess.Popen[bytes] | None = None


def chrome_binary() -> Path:
    """Resolve the Chrome binary from the environment, then the usual install locations."""
    override = os.environ.get("RELAY_CHROME")
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return path
        raise ProviderUnavailable(
            f"RELAY_CHROME points at {path}, which does not exist. Fix the path or unset it."
        )

    for candidate in CHROME_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path

    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise ProviderUnavailable(
        "Chrome was not found. Install Google Chrome, or set RELAY_CHROME to its binary."
    )


def launch() -> subprocess.Popen[bytes]:
    """Start Chrome on the relay profile, detached from this process.

    Returns immediately; readiness is ``ensure_running``'s job.
    """
    global _process

    if _process is not None and _process.poll() is None:
        return _process

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.chmod(0o700)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    binary = chrome_binary()
    argv = [str(binary), f"--user-data-dir={PROFILE_DIR}", *LAUNCH_FLAGS, "about:blank"]
    log.info("launching %s on CDP port %d", binary, CDP_PORT)

    # Detach: Chrome must outlive the daemon so a restart does not log the user out.
    with (LOG_DIR / "chrome.log").open("ab") as sink:
        _process = subprocess.Popen(
            argv,
            stdout=sink,
            stderr=sink,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return _process


async def is_up(timeout_s: float = 0.5) -> bool:
    """True when Chrome is already listening for CDP on this machine."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(f"{CDP_URL}/json/version")
    except (httpx.HTTPError, OSError):
        return False
    return response.status_code == 200


async def ensure_running(timeout_s: float = 25.0) -> str:
    """Attach if Chrome is up, otherwise launch it and wait for CDP. Returns the CDP URL."""
    if await is_up():
        return CDP_URL

    launch()

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await is_up():
            return CDP_URL
        await asyncio.sleep(0.5)

    raise ProviderUnavailable(
        f"Chrome did not open a debugging port at {CDP_URL} within {timeout_s:.0f}s. "
        "Run `relay launch` and check `~/.relay/logs/chrome.log`."
    )


async def connect() -> Browser:
    """Return a live CDP connection, connecting at most once per process."""
    global _playwright, _browser

    if _browser is not None and _browser.is_connected():
        return _browser

    await ensure_running()

    if _playwright is None:
        _playwright = await async_playwright().start()

    try:
        _browser = await _playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception as exc:  # Playwright raises a variety of connection errors here.
        _browser = None
        raise ProviderUnavailable(
            f"could not attach to Chrome at {CDP_URL}: {exc}. "
            "Try `relay launch`, or close the relay profile window and retry."
        ) from exc

    log.info("attached to Chrome over CDP")
    return _browser


async def new_page(url: str | None = None) -> Page:
    """Open a fresh tab in the relay profile, optionally navigating it."""
    browser = await connect()
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await context.new_page()
    page.set_default_timeout(15_000)
    page.set_default_navigation_timeout(45_000)

    if url:
        await page.goto(url, wait_until="domcontentloaded")
    return page


async def disconnect() -> None:
    """Tear down the CDP connection. Distance from the process, not from Chrome."""
    global _browser, _playwright

    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            log.debug("browser close failed", exc_info=True)
        _browser = None

    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            log.debug("playwright stop failed", exc_info=True)
        _playwright = None
