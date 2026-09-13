"""bot.py's Chromium flags, before and after the fix.

Before: --single-process is in the args list, directly above a comment
saying it was removed. A single-process Chromium serves exactly one
BrowserContext, so the second user kills the browser and takes the first
user's report with it.

After: those flags are gone and the process count is capped instead.

    PYTHONPATH=. python tests/test_bot_args.py
"""

import asyncio
import os
import sys

from playwright.async_api import async_playwright

COMMON = [
    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    "--disable-gpu", "--disable-software-rasterizer", "--disable-extensions",
    "--disable-background-networking", "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--js-flags=--max-old-space-size=512",
]
BEFORE = COMMON[:5] + ["--single-process", "--no-zygote"] + COMMON[5:]
AFTER = COMMON[:5] + ["--renderer-process-limit=1", "--process-per-site"] + COMMON[5:]


async def two_users(p, args, port):
    """Two users, each with their own context, as carfax_web_api does."""
    kwargs = {"headless": True, "args": args + [f"--remote-debugging-port={port}"]}
    path = os.environ.get("VINPRO_CHROMIUM_PATH", "").strip()
    if path:
        kwargs["executable_path"] = path
    owner = await p.chromium.launch(**kwargs)
    shared = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    try:
        pages = []
        for name in ("A", "B"):
            ctx = await shared.new_context()
            page = await ctx.new_page()
            await page.set_content(f"<h1 id='r'>user {name}</h1>")
            pages.append((name, page))
        for name, page in pages:
            assert await page.locator("#r").count() == 1, name
        return True, "both users rendered"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"
    finally:
        try:
            await owner.close()
        except Exception:
            pass


async def main():
    async with async_playwright() as p:
        ok_before, msg_before = await two_users(p, BEFORE, 9388)
        print(f"BEFORE (--single-process): {'OK' if ok_before else 'FAILED'} - {msg_before}")
        if ok_before:
            sys.exit("FAIL: the old flags should break with two contexts")
        print("PASS  the old flags do break the second user, as reported")

        ok_after, msg_after = await two_users(p, AFTER, 9389)
        print(f"AFTER  (fixed flags):      {'OK' if ok_after else 'FAILED'} - {msg_after}")
        if not ok_after:
            sys.exit("FAIL: the fixed flags should serve two users")
        print("PASS  the fixed flags serve both users")


asyncio.run(main())
