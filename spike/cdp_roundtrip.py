"""Phase 0 spike: prove the round-trip before building anything on it.

This is a throwaway experiment, not production code. It deliberately duplicates the selectors and
uses ``print`` — neither belongs in ``src/``. Delete it once Phase 1 passes.

    uv run python spike/cdp_roundtrip.py --runs 10

Exit code is non-zero unless every run comes back with OK. The failure mode worth hunting is not
"it never works" but "it works seven times and hangs on the eighth".
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.async_api import Browser, Locator, Page, async_playwright

PROFILE_DIR = Path.home() / ".relay" / "chrome"
OUT_DIR = Path(__file__).parent / "out"

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)

# Mirrors src/relay/drivers/*/selectors.json at the time of writing. Kept inline on purpose: the
# spike must not depend on the code it is meant to validate.
PROVIDERS: dict[str, dict[str, object]] = {
    "chatgpt": {
        "url": "https://chatgpt.com/",
        "composer": [
            "div#prompt-textarea",
            'div.ProseMirror[contenteditable="true"]',
            'textarea[data-testid="prompt-textarea"]',
            '[contenteditable="true"][role="textbox"]',
        ],
        "assistant": [
            '[data-message-author-role="assistant"]',
            "div.agent-turn",
            "article",
        ],
    },
    "gemini": {
        "url": "https://gemini.google.com/app",
        "composer": [
            'rich-textarea div[contenteditable="true"]',
            'div[contenteditable="true"][role="textbox"]',
            "textarea",
        ],
        "assistant": ["model-response", "message-content"],
    },
    "claude": {
        "url": "https://claude.ai/new",
        "composer": [
            'div[contenteditable="true"].ProseMirror',
            'div[contenteditable="true"][role="textbox"]',
        ],
        "assistant": ["div.font-claude-message", "div[data-testid='chat-message']"],
    },
}

PROMPT = "Reply with exactly: OK"
STABLE_S = 1.2
POLL_S = 0.4


def chrome_binary() -> Path:
    for candidate in CHROME_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return Path(found)
    raise SystemExit("Chrome not found. Install Google Chrome or set RELAY_CHROME.")


def launch_chrome(port: int) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.chmod(0o700)
    binary = chrome_binary()
    print(f"launching {binary} on port {port}")

    log_dir = PROFILE_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with (log_dir / "chrome-spike.log").open("ab") as sink:
        subprocess.Popen(
            [
                str(binary),
                f"--user-data-dir={PROFILE_DIR}",
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=sink,
            stderr=sink,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


async def cdp_ready(port: int, timeout_s: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=0.5) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"http://127.0.0.1:{port}/json/version")
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    return False


async def resolve(page: Page, candidates: list[str], timeout_s: float = 15.0) -> Locator:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for selector in candidates:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    return locator
            except Exception:
                continue
        await asyncio.sleep(0.25)
    raise TimeoutError(f"none of {candidates} matched")


async def last_turn_text(page: Page, assistant: list[str]) -> str:
    for selector in assistant:
        locator = page.locator(selector)
        try:
            if await locator.count():
                return (await locator.last.inner_text()).strip()
        except Exception:
            continue
    return ""


async def wait_for_answer(page: Page, assistant: list[str], timeout_s: float) -> tuple[str, bool]:
    deadline = time.monotonic() + timeout_s
    last = ""
    stable_since: float | None = None

    while time.monotonic() < deadline:
        current = await last_turn_text(page, assistant)
        if current and current == last:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= STABLE_S:
                return current, False
        else:
            last = current
            stable_since = None
        await asyncio.sleep(POLL_S)

    return last, True


async def one_run(browser: Browser, provider: str, assistant: list[str], timeout_s: float) -> bool:
    config = PROVIDERS[provider]
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await context.new_page()

    try:
        await page.goto(str(config["url"]), wait_until="domcontentloaded")
        composer = await resolve(page, list(config["composer"]))  # type: ignore[arg-type]

        await composer.click()
        await page.keyboard.insert_text(PROMPT)
        await page.keyboard.press("Enter")

        text, truncated = await wait_for_answer(page, assistant, timeout_s)
        ok = "ok" in text.lower()
        status = "PASS" if ok else "FAIL"
        note = " (timeout)" if truncated else ""
        print(f"  {status}{note}  {text[:160]!r}")
        return ok
    except Exception as exc:
        print(f"  FAIL  {type(exc).__name__}: {exc}")
        OUT_DIR.mkdir(exist_ok=True)
        shot = OUT_DIR / f"fail-{provider}-{int(time.time())}.png"
        try:
            await page.screenshot(path=str(shot))
            print(f"        screenshot: {shot}")
        except Exception:
            pass
        return False
    finally:
        await page.close()


async def main_async(args: argparse.Namespace) -> int:
    provider = args.provider
    config = PROVIDERS[provider]
    assistant = list(config["assistant"])  # type: ignore[arg-type]

    if not await cdp_ready(args.port, timeout_s=0.5):
        launch_chrome(args.port)
        if not await cdp_ready(args.port):
            print("FAIL: Chrome never opened a debugging port")
            return 2

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")

    print(f"{provider}: {args.runs} runs, prompt {PROMPT!r}")
    results = [await one_run(browser, provider, assistant, args.timeout) for _ in range(args.runs)]

    await browser.close()
    await playwright.stop()

    passed = sum(results)
    print(f"\n{passed}/{len(results)} OK")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="chatgpt")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--timeout", type=float, default=120.0)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
