"""Find a Chromium launch configuration that survives on this host.

Shared hosting (cPanel / CloudLinux) breaks Chromium in a handful of
well-known ways: missing shared libraries, an LVE process limit that the
multi-process browser blows through, a tiny /dev/shm, or a blocked sandbox.
Each shows up as the same unhelpful symptom - the browser exits immediately,
usually with SIGTRAP or SIGSEGV.

This probe tries the configurations in order of preference and prints the
first one that actually renders a page, plus the exact settings to put in
.env.vinpro.

    PYTHONPATH=. python deploy/probe_chromium.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

from playwright.async_api import async_playwright

BASE_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
]

# Ordered best -> most constrained. "single process" is last-resort but is
# frequently the only thing that fits inside a CloudLinux LVE process limit.
CONFIGS = [
    ("default", BASE_ARGS, {}),
    (
        "no-zygote",
        BASE_ARGS + ["--no-zygote"],
        {},
    ),
    (
        "single-process",
        BASE_ARGS + ["--single-process", "--no-zygote"],
        {
            "VINPRO_SINGLE_PROCESS": "1",
            "VINPRO_FRESH_BROWSER_PER_REQUEST": "1",
            "VINPRO_MAX_CONCURRENT_RENDERS": "1",
        },
    ),
    (
        "single-process + low memory",
        BASE_ARGS
        + [
            "--single-process",
            "--no-zygote",
            "--disable-software-rasterizer",
            "--disable-extensions",
            "--disable-background-networking",
            "--renderer-process-limit=1",
            "--js-flags=--max-old-space-size=256",
        ],
        {
            "VINPRO_SINGLE_PROCESS": "1",
            "VINPRO_LOW_MEMORY": "1",
            "VINPRO_FRESH_BROWSER_PER_REQUEST": "1",
            "VINPRO_MAX_CONCURRENT_RENDERS": "1",
        },
    ),
]

EXECUTABLE = os.environ.get("VINPRO_CHROMIUM_PATH", "").strip()


async def try_config(playwright, name, args):
    browser = None
    try:
        launch_kwargs = {"headless": True, "args": args}
        if EXECUTABLE:
            launch_kwargs["executable_path"] = EXECUTABLE
        browser = await playwright.chromium.launch(**launch_kwargs)
        # One context only: --single-process Chromium dies on the second one.
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content("<h1 id='ok'>ready</h1>")
        await page.locator("#ok").wait_for(state="visible", timeout=20_000)
        assert await page.locator("#ok").count() == 1
        text = await page.inner_text("#ok")
        assert text == "ready", text
        await context.close()
        return True, ""
    except Exception:
        return False, traceback.format_exc(limit=3)
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


async def main():
    print("Chromium executable:", EXECUTABLE or "(playwright bundled)")
    print("Probing launch configurations...\n")

    async with async_playwright() as playwright:
        for name, args, env in CONFIGS:
            print(f"--- {name}")
            ok, err = await try_config(playwright, name, args)
            if ok:
                print(f"    WORKS\n")
                print("=" * 60)
                print(f"Working configuration: {name}")
                print("Add these lines to .env.vinpro:\n")
                for key, value in env.items():
                    print(f"    {key}={value}")
                if EXECUTABLE:
                    print(f"    VINPRO_CHROMIUM_PATH={EXECUTABLE}")
                if not env and not EXECUTABLE:
                    print("    (no extra settings needed)")
                print("=" * 60)
                return 0
            print("    failed:")
            print("    " + err.strip().replace("\n", "\n    ") + "\n")

    print("=" * 60)
    print("No configuration worked. The most common remaining causes:")
    print("  * missing system libraries  -> run deploy/probe_chromium.sh,")
    print("    which lists them with ldd")
    print("  * CloudLinux LVE limits     -> ask the host to raise NPROC/PMEM")
    print("    for this account, or move the bot to a VPS")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
