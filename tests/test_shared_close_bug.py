"""The reported bug, reproduced - and shown fixed.

carfax_web_api.py keeps a module-level _shared_browser, a CDP connection to
the Chromium bot.py launched. Every user's page is created through it. When
one request takes the reconnect path it calls _shared_browser.close(), which
closes every page created through that connection - including another user's
report, mid-render.

That is exactly what the users saw:

    Locator.count: Target page, context or browser has been closed
    Locator.wait_for: Target page, context or browser has been closed

and why it hit one user while the other still got their PDF: the browser
itself survives, so whoever was not holding a page through that connection
was unaffected.

    PYTHONPATH=. python tests/test_shared_close_bug.py
"""

import asyncio
import os
import sys

from playwright.async_api import async_playwright

PORT = int(os.environ.get("VINPRO_TEST_CDP_PORT", "9366"))
CDP = f"http://127.0.0.1:{PORT}"

EXPECTED = "Target page, context or browser has been closed"


def launch_kwargs():
    kwargs = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            f"--remote-debugging-port={PORT}",
        ],
    }
    path = os.environ.get("VINPRO_CHROMIUM_PATH", "").strip()
    if path:
        kwargs["executable_path"] = path
    return kwargs


async def reproduce_bug(p, owner):
    """The old code path. Must still fail, or the test proves nothing."""
    shared = await p.chromium.connect_over_cdp(CDP)
    ctx = await shared.new_context()
    user_a = await ctx.new_page()
    await user_a.set_content("<h1 id='r'>user A report</h1>")

    await shared.close()  # carfax_web_api.py, the reconnect path
    await asyncio.sleep(0.3)

    for label, coro in (
        ("Locator.count", user_a.locator("#r").count()),
        ("Locator.wait_for", user_a.locator("#r").wait_for(timeout=3000)),
    ):
        try:
            await coro
        except Exception as exc:
            assert EXPECTED in str(exc), f"unexpected error for {label}: {exc}"
            print(f"PASS  bug reproduced - {label}: {EXPECTED}")
        else:
            sys.exit(f"FAIL: {label} should have failed on the old path")

    assert owner.is_connected(), "the browser itself should survive"
    print("PASS  the browser survived, which is why the other user still got a PDF")


async def show_fixed(owner):
    """The same reconnect, through the manager. Must not disturb anyone."""
    os.environ["VINPRO_CDP_URL"] = CDP
    for mod in [m for m in sys.modules if m.startswith("vinpro")]:
        del sys.modules[mod]
    from vinpro.browser_manager import manager, render_with_retry

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_user(page, _):
        await page.set_content("<h1 id='r'>user A report</h1>")
        started.set()
        await release.wait()  # still mid-render while B reconnects
        await page.locator("#r").wait_for(state="visible", timeout=10_000)
        return await page.locator("#r").count()

    task = asyncio.create_task(render_with_retry(slow_user, "A"))
    await asyncio.wait_for(started.wait(), timeout=20)

    await manager.drop_browser()  # user B's reconnect
    print("PASS  a reconnect happened while user A was mid-render")

    release.set()
    assert await asyncio.wait_for(task, timeout=30) == 1
    print("PASS  user A's report completed anyway")

    assert owner.is_connected(), "the owner's browser must be untouched"
    await manager.shutdown()
    assert owner.is_connected(), "shutdown must not close someone else's browser"
    print("PASS  the owner's browser was never touched")


async def main():
    async with async_playwright() as p:
        owner = await p.chromium.launch(**launch_kwargs())
        try:
            await reproduce_bug(p, owner)
            await show_fixed(owner)
        finally:
            try:
                await owner.close()
            except Exception:
                pass
    print("\nALL PASS")


asyncio.run(main())
