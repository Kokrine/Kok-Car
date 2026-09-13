"""Find out why Playwright cannot launch a Chromium that runs fine by hand.

The host turned out to be healthy - libraries resolved, the binary prints
its version, memory and limits are generous - and the bot itself launches
Chromium successfully every day. So the failure is specific to how Playwright
starts it, and the ordinary error message ("Target page, context or browser
has been closed") hides the reason.

This runs the launch again with Playwright's own browser logging enabled, so
the browser's stderr is captured, and checks the things that kill a browser
silently: a profile directory that cannot be written, a noexec /tmp, a full
disk quota, an already-running instance.

    python deploy/probe_deep.py
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")


def run(cmd, shell=False, env=None, timeout=90):
    try:
        p = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "", "(timed out)"
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"(failed: {exc})"


def head(title):
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def find_binaries():
    roots = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        os.path.join(HOME, ".cache/ms-playwright"),
    ]
    found = []
    for root in roots:
        if root and os.path.isdir(root):
            for pat in ("*/chrome-linux*/chrome",
                        "*/chrome-headless-shell-linux*/chrome-headless-shell"):
                found.extend(glob.glob(os.path.join(root, pat)))
    return sorted(set(found))


def check_environment():
    head("ENVIRONMENT")
    rc, out, _ = run(["pgrep", "-fa", "chrome"])
    running = [l for l in out.splitlines() if l.strip()]
    print(f"chrome processes already running: {len(running)}")
    for line in running[:6]:
        print(f"    {line[:160]}")

    mount_info = run("mount | grep ' /tmp ' || echo '(/tmp is not a separate mount)'",
                     shell=True)[1].strip()
    tmp_free = run("df -h /tmp | tail -1", shell=True)[1].strip()
    home_free = run("df -h ~ | tail -1", shell=True)[1].strip()
    print("")
    print(f"/tmp mount : {mount_info}")
    print(f"/tmp free  : {tmp_free}")
    print(f"home free  : {home_free}")
    rc, out, err = run(["quota", "-s"])
    print(f"quota      : {(out or err).strip()[:400] or '(no quota command)'}")

    # A profile directory that cannot be written kills Chromium instantly.
    for d in ("/tmp", HOME):
        try:
            probe = tempfile.mkdtemp(dir=d, prefix="vinpro_w_")
            with open(os.path.join(probe, "x"), "w") as fh:
                fh.write("ok")
            shutil.rmtree(probe)
            print(f"writable   : {d}  yes")
        except Exception as exc:  # noqa: BLE001
            print(f"writable   : {d}  NO - {exc}")


def check_direct(binary):
    head(f"DIRECT LAUNCH  {os.path.basename(binary)}")
    base = [
        binary, "--headless", "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-dev-shm-usage", "--disable-gpu",
    ]
    for label, extra in (
        ("no profile dir", []),
        ("profile in /tmp", [f"--user-data-dir={tempfile.mkdtemp(prefix='vinpro_tmp_')}"]),
        ("profile in home", [f"--user-data-dir={tempfile.mkdtemp(prefix='vinpro_home_', dir=HOME)}"]),
    ):
        rc, out, err = run(base + extra + ["--dump-dom", "about:blank"], timeout=60)
        status = "OK" if rc == 0 else f"exit={rc}"
        print(f"\n--- {label}: {status}")
        noise = ("Fontconfig", "dbus", "cpufreq", "GPU", "gbm", "vulkan")
        for line in (err or "").splitlines():
            if line.strip() and not any(n in line for n in noise):
                print(f"    {line[:200]}")
        if rc == 0 and out.strip():
            print(f"    rendered {len(out)} bytes of DOM")


def check_playwright():
    head("PLAYWRIGHT LAUNCH  (with browser stderr captured)")
    script = '''
import asyncio, sys
from playwright.async_api import async_playwright
ARGS = ["--no-sandbox", "--disable-setuid-sandbox",
        "--disable-dev-shm-usage", "--disable-gpu"]
async def attempt(label, **kw):
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(headless=True, args=ARGS, **kw)
            page = await b.new_page()
            await page.set_content("<h1 id=ok>ready</h1>")
            n = await page.locator("#ok").count()
            await b.close()
            print(f"RESULT {label}: OK (locator count={n})")
            return True
        except Exception as exc:
            print(f"RESULT {label}: FAILED {type(exc).__name__}: {str(exc)[:200]}")
            return False
async def main():
    ok = await attempt("default")
    if not ok:
        await attempt("chrome channel", channel="chromium")
asyncio.run(main())
'''
    env = dict(os.environ, DEBUG="pw:browser")
    rc, out, err = run([sys.executable, "-c", script], env=env, timeout=180)
    for line in out.splitlines():
        if line.startswith("RESULT"):
            print(f"  {line}")
    print("\n  browser stderr (the reason, if any):")
    interesting = [
        l for l in err.splitlines()
        if "pw:browser" in l and not any(
            n in l for n in ("Fontconfig", "dbus", "cpufreq", "GPU", "gbm", "vulkan")
        )
    ]
    for line in interesting[-40:]:
        print(f"    {line[:220]}")
    if not interesting:
        print("    (nothing captured)")


def check_persistent():
    head("PLAYWRIGHT WITH A PROFILE IN HOME")
    script = f'''
import asyncio, tempfile
from playwright.async_api import async_playwright
async def main():
    d = tempfile.mkdtemp(prefix="vinpro_pc_", dir="{HOME}")
    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                d, headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu"])
            page = await ctx.new_page()
            await page.set_content("<h1 id=ok>ready</h1>")
            n = await page.locator("#ok").count()
            await ctx.close()
            print(f"RESULT persistent-context: OK (locator count={{n}})")
        except Exception as exc:
            print(f"RESULT persistent-context: FAILED {{type(exc).__name__}}: {{str(exc)[:200]}}")
asyncio.run(main())
'''
    rc, out, err = run([sys.executable, "-c", script], timeout=180)
    for line in out.splitlines():
        if line.startswith("RESULT"):
            print(f"  {line}")


def main() -> int:
    check_environment()
    binaries = find_binaries()
    if not binaries:
        print("\nNo Chromium binary found.")
        return 1
    check_direct(binaries[-1])
    check_playwright()
    check_persistent()
    head("DONE")
    print("Send this whole output back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
