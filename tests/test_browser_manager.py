"""Exercise the real failure mode: concurrent renders + a killed browser.

Run from the repository root:

    PYTHONPATH=. python tests/test_browser_manager.py

Both modes are worth checking:

    VINPRO_FRESH_BROWSER_PER_REQUEST=0 PYTHONPATH=. python tests/test_browser_manager.py
    VINPRO_FRESH_BROWSER_PER_REQUEST=1 PYTHONPATH=. python tests/test_browser_manager.py
"""
import asyncio, sys
from vinpro.browser_manager import manager, render_with_retry, is_closed_error

async def job(page, name):
    await page.set_content(f"<h1 id='ok'>{name}</h1>")
    await page.locator("#ok").wait_for(state="visible", timeout=15_000)
    assert await page.locator("#ok").count() == 1
    return await page.inner_text("#ok")

async def main():
    # 1. single render
    assert await render_with_retry(job, "one") == "one"
    print("PASS  single render")

    # 2. five concurrent users - the scenario that used to close the shared browser
    results = await asyncio.gather(*(render_with_retry(job, f"user{i}") for i in range(5)))
    assert results == [f"user{i}" for i in range(5)], results
    print("PASS  5 concurrent renders:", results)

    # 3. browser killed mid-flight -> must be relaunched, not raised at the user
    async def kill_then_work(page, name):
        if not getattr(kill_then_work, "killed", False):
            kill_then_work.killed = True
            await manager.drop_browser()          # simulates OOM / worker recycle
            await page.locator("#nope").count()   # -> "browser has been closed"
        return await job(page, name)
    assert await render_with_retry(kill_then_work, "recovered") == "recovered"
    print("PASS  recovered from a dead browser")

    # 4. a real page bug must NOT be silently retried away
    async def broken(page, _):
        await page.set_content("<p>empty</p>")
        await page.locator("#missing").wait_for(timeout=1000)
    try:
        await render_with_retry(broken, "x")
    except Exception as exc:
        assert not is_closed_error(exc), exc
        print("PASS  real timeout surfaces:", type(exc).__name__)
    else:
        sys.exit("FAIL: broken job should have raised")

    # 5. still usable afterwards
    assert await render_with_retry(job, "after") == "after"
    print("PASS  manager healthy after failures")
    await manager.shutdown()
    print("PASS  clean shutdown")

asyncio.run(main())
