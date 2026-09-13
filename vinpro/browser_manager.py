"""Playwright browser lifecycle manager.

Fixes the class of errors that surface in the Telegram bot as:

    Locator.count: Target page, context or browser has been closed
    Locator.wait_for: Target page, context or browser has been closed

Those errors never mean "bad VIN" or "site blocked us". They mean the
browser / context / page was closed by *something else* while this request
was still using it. In a bot that serves several users the usual causes are:

  1. One global browser shared by every request. The first request to
     finish closes it; every other in-flight request dies mid-locator.
  2. A crashed Chromium (out of memory on the server). The Python object
     survives, the process behind it does not.
  3. The hosting process manager (Passenger / LiteSpeed on cPanel) recycling
     the worker while a report is being rendered, which kills the child
     Chromium with it.

The manager below removes cause 1 and 2 and makes 3 survivable:

  * every request gets its own BrowserContext (never a shared page);
  * a serialising semaphore keeps concurrent renders bounded;
  * the shared browser is health-checked before use and relaunched if dead;
  * "closed" failures are retried once on a brand new browser.

Usage in a handler:

    from vinpro.browser_manager import render_with_retry

    async def build_report(page, vin):
        await page.goto(f"https://example.com/vin/{vin}")
        await page.locator("#report").wait_for(timeout=60_000)
        return await page.pdf(format="A4")

    pdf_bytes = await render_with_retry(build_report, vin)

Configuration (environment variables):

    VINPRO_MAX_CONCURRENT_RENDERS   default 1  - parallel reports allowed
    VINPRO_FRESH_BROWSER_PER_REQUEST default 0 - 1 = launch/close per request
                                                 (slower, but bulletproof on
                                                 memory-limited cPanel hosts)
    VINPRO_NAV_TIMEOUT_MS           default 60000
    VINPRO_HEADLESS                 default 1
    VINPRO_CHROMIUM_PATH            default '' - path to an existing Chromium
                                                 binary, for hosts where
                                                 `playwright install` is blocked
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError

log = logging.getLogger(__name__)

T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


MAX_CONCURRENT_RENDERS = max(1, _env_int("VINPRO_MAX_CONCURRENT_RENDERS", 1))
FRESH_BROWSER_PER_REQUEST = _env_bool("VINPRO_FRESH_BROWSER_PER_REQUEST", False)
NAV_TIMEOUT_MS = _env_int("VINPRO_NAV_TIMEOUT_MS", 60_000)
HEADLESS = _env_bool("VINPRO_HEADLESS", True)
CHROMIUM_PATH = os.environ.get("VINPRO_CHROMIUM_PATH", "").strip()

# Chromium flags that matter on shared hosting: /dev/shm is tiny there, and
# the sandbox is usually unavailable inside cPanel's restricted environment.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--no-first-run",
    "--disable-background-networking",
]

_CLOSED_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "browser has disconnected",
    "connection closed",
    "page crashed",
    "target crashed",
    "browser has been closed",
    "playwright is not running",
)


def is_closed_error(exc: BaseException) -> bool:
    """True when the failure is a dead browser/context/page, not a page bug."""
    if not isinstance(exc, (PlaywrightError, ConnectionError)):
        return False
    return any(marker in str(exc).lower() for marker in _CLOSED_MARKERS)


class BrowserManager:
    """Owns one Playwright + Browser and hands out isolated contexts.

    The browser is never closed by a request. Only :meth:`shutdown` (called on
    bot shutdown) or a detected crash closes it, so one user finishing can no
    longer pull the browser out from under another user.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

    async def _launch(self) -> Browser:
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        log.info(
            "launching chromium (headless=%s, executable=%s)",
            HEADLESS,
            CHROMIUM_PATH or "bundled",
        )
        launch_kwargs: dict[str, Any] = {"headless": HEADLESS, "args": LAUNCH_ARGS}
        if CHROMIUM_PATH:
            # Shared hosts often block `playwright install`; point at a
            # system Chromium instead of the bundled download.
            launch_kwargs["executable_path"] = CHROMIUM_PATH
        return await self._playwright.chromium.launch(**launch_kwargs)

    async def _get_browser(self) -> Browser:
        """Return a live browser, relaunching it if the previous one died."""
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._browser is not None:
                log.warning("chromium is no longer connected - relaunching")
                try:
                    await self._browser.close()
                except Exception:  # noqa: BLE001 - already dead, nothing to do
                    pass
                self._browser = None
            self._browser = await self._launch()
            return self._browser

    async def drop_browser(self) -> None:
        """Force the next request to start from a freshly launched browser."""
        async with self._lock:
            browser, self._browser = self._browser, None
            if browser is not None:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass

    @asynccontextmanager
    async def page(self, **context_kwargs: Any) -> AsyncIterator[Page]:
        """Yield a page in a private context; close only what we created.

        Concurrency is bounded by the semaphore, so two users can no longer
        fight over the same Chromium process (and its memory).
        """
        async with self._semaphore:
            own_browser: Browser | None = None
            if FRESH_BROWSER_PER_REQUEST:
                browser = own_browser = await self._launch()
            else:
                browser = await self._get_browser()

            context: BrowserContext | None = None
            try:
                context = await browser.new_context(**context_kwargs)
                context.set_default_timeout(NAV_TIMEOUT_MS)
                context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
                page = await context.new_page()
                yield page
            finally:
                # Close our own context/browser only - never a shared one.
                if context is not None:
                    try:
                        await context.close()
                    except Exception:  # noqa: BLE001
                        pass
                if own_browser is not None:
                    try:
                        await own_browser.close()
                    except Exception:  # noqa: BLE001
                        pass

    async def shutdown(self) -> None:
        """Call once when the bot stops (e.g. Application.post_shutdown)."""
        await self.drop_browser()
        async with self._lock:
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._playwright = None


manager = BrowserManager()


async def render_with_retry(
    job: Callable[..., Awaitable[T]],
    *args: Any,
    attempts: int = 2,
    context_kwargs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Run ``job(page, *args, **kwargs)`` and retry once if the browser died.

    Only "closed / crashed" failures are retried - a genuine timeout or a
    missing element is raised immediately so the bug is not hidden behind
    silent retries.
    """
    context_kwargs = context_kwargs or {}
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            async with manager.page(**context_kwargs) as page:
                return await job(page, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last_error = exc
            if not is_closed_error(exc) or attempt == attempts:
                raise
            log.warning(
                "browser died during attempt %s/%s (%s) - relaunching",
                attempt,
                attempts,
                exc,
            )
            await manager.drop_browser()
            await asyncio.sleep(2 * attempt)

    assert last_error is not None  # pragma: no cover - loop always raises
    raise last_error
