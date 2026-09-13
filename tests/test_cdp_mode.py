"""Prove that CDP mode never kills the browser it attached to.

This is the shape the bot uses: one process launches Chromium with a remote
debugging port, another attaches over CDP. The bug being fixed is that the
attaching side called browser.close(), tearing down the browser that other
requests were still rendering in.

    PYTHONPATH=. python tests/test_cdp_mode.py
"""

import asyncio
import os
import sys

from playwright.async_api import async_playwright

PORT = int(os.environ.get("VINPRO_TEST_CDP_PORT", "9333"))
CDP = f"http://127.0.0.1:{PORT}"


async def main():
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            f"--remote-debugging-port={PORT}"]
    launch_kwargs = {"headless": True, "args": args}
    path = os.environ.get("VINPRO_CHROMIUM_PATH", "").strip()
    if path:
        launch_kwargs["executable_path"] = path

    async with async_playwright() as p:
        # The "bot.py" side: owns the browser.
        owner = await p.chromium.launch(**launch_kwargs)
        owner_page = await owner.new_page()
        await owner_page.set_content("<h1 id='owner'>owner page</h1>")
        print("PASS  owner launched a browser and opened a page")

        # The "carfax_web_api.py" side: attaches to it.
        os.environ["VINPRO_CDP_URL"] = CDP
        for mod in [m for m in sys.modules if m.startswith("vinpro")]:
            del sys.modules[mod]
        from vinpro.browser_manager import manager, render_with_retry

        async def job(page, name):
            await page.set_content(f"<h1 id='ok'>{name}</h1>")
            await page.locator("#ok").wait_for(state="visible", timeout=15_000)
            assert await page.locator("#ok").count() == 1
            return await page.inner_text("#ok")

        assert await render_with_retry(job, "attached") == "attached"
        print("PASS  attached over CDP and rendered")

        results = await asyncio.gather(
            *(render_with_retry(job, f"user{i}") for i in range(4))
        )
        assert results == [f"user{i}" for i in range(4)], results
        print("PASS  4 concurrent renders over CDP:", results)

        # The old bug: this used to close the owner's browser.
        await manager.drop_browser()
        await manager.shutdown()
        if not owner.is_connected():
            sys.exit("FAIL: shutdown killed the owner's browser")
        print("PASS  owner's browser survived drop_browser + shutdown")

        # The owner's own page must still be usable.
        assert await owner_page.inner_text("#owner") == "owner page"
        print("PASS  owner's page still works")

        # And the attached side still works after reconnecting.
        assert await render_with_retry(job, "after") == "after"
        print("PASS  reattached and rendered again")
        await manager.shutdown()

        await owner.close()
        print("PASS  owner closed its own browser")


asyncio.run(main())
