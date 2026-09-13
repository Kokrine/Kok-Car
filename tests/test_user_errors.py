"""Nothing about the source site may reach a user.

    PYTHONPATH=. python tests/test_user_errors.py
"""

import sys

from playwright.async_api import Error as PlaywrightError

from vinpro.user_errors import BLOCKED_WORDS, log_message, scrub, user_message

# Real shapes of Playwright failures, which carry URLs, paths and ports.
SAMPLES = [
    'Locator.count: Target page, context or browser has been closed',
    'page.goto: net::ERR_CONNECTION_REFUSED at https://www.cargopolo.com/ka/login',
    'Timeout 60000ms exceeded.\nwaiting for navigation to "https://www.cargopolo.com/report/X"',
    'BrowserType.launch: Executable does not exist at /home/mycarge/.cache/ms-playwright/chromium-1223/chrome',
    'connect_over_cdp: connect ECONNREFUSED 127.0.0.1:9222',
    'ბრაუზერთან მიერთება ვერ მოხერხდა http://127.0.0.1:9222-ზე 5 მცდელობის შემდეგ',
    'waiting for locator("#report-container") to be visible',
    'Navigation to CARGOPOLO.COM failed',
]

FORBIDDEN = [
    "cargopolo", "CARGOPOLO", "cargopolo.com",
    "127.0.0.1", "9222", "ms-playwright", "/home/mycarge",
    "#report-container", "https://",
]

failures = 0

print("--- user_message() must be fixed text, never derived from the error")
for sample in SAMPLES:
    msg = user_message(PlaywrightError(sample))
    for bad in FORBIDDEN:
        if bad.lower() in msg.lower():
            print(f"  LEAK {bad!r} in message for: {sample[:50]}")
            failures += 1
    if "Locator" in msg or "Target page" in msg:
        print(f"  LEAK raw Playwright text for: {sample[:50]}")
        failures += 1
print(f"  checked {len(SAMPLES)} errors, all mapped to fixed messages")

print("\n--- scrub() must clean text that is shown anyway")
for sample in SAMPLES:
    cleaned = scrub(sample)
    for bad in FORBIDDEN:
        if bad.lower() in cleaned.lower():
            print(f"  LEAK {bad!r} survived scrub: {cleaned[:70]}")
            failures += 1
print(f"  checked {len(SAMPLES)} errors, nothing identifying survived")

print("\n--- log_message() is detailed but still scrubbed")
logged = log_message(PlaywrightError(SAMPLES[1]))
if "cargopolo" in logged.lower():
    print(f"  LEAK in log message: {logged}")
    failures += 1
print(f"  {logged}")

print("\n--- the classifier picks sensible messages")
cases = [
    (PlaywrightError("Locator.count: Target page, context or browser has been closed"), "დატვირთულია"),
    (PlaywrightError("Timeout 60000ms exceeded."), "მეტი დრო"),
    (LookupError("1HGCM82633A004352"), "ვერ მოიძებნა"),
    (ValueError("something odd"), "ვერ მოხერხდა"),
]
for exc, expected in cases:
    msg = user_message(exc)
    if expected not in msg:
        print(f"  WRONG message for {type(exc).__name__}: {msg!r}")
        failures += 1
    else:
        print(f"  {type(exc).__name__:<16} -> {msg.splitlines()[0]}")

print("\n--- every message mentions the credit was not charged")
for exc, _ in cases:
    if "კრედიტი არ ჩამოგეჭრათ" not in user_message(exc):
        print(f"  MISSING credit note for {type(exc).__name__}")
        failures += 1

print(f"\nblocked words: {BLOCKED_WORDS}")
if failures:
    sys.exit(f"\n{failures} FAILURE(S)")
print("\nALL PASS")
