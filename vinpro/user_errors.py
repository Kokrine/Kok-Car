"""Safe, short messages for users - never raw internals.

The bot has been sending Playwright's own text straight to Telegram:

    ვერ მოხერხდა რეპორტის მიღება: Locator.count: Target page, context or
    browser has been closed

That is how internals reach users, and Playwright errors routinely carry the
URL being navigated ("waiting for navigation to https://..."), file paths,
ports and selectors. Anything the report is sourced from can leak that way.

So nothing derived from an exception is ever shown. `user_message()` maps the
failure to a fixed sentence, and `scrub()` is a second line of defence for
text that must be shown anyway: it removes URLs, bare domains, host:port
pairs, IPs, filesystem paths, and any word on the blocklist.

Configure the blocklist with VINPRO_SCRUB_WORDS (comma separated). The
source site is blocked by default.
"""

from __future__ import annotations

import os
import re

DEFAULT_BLOCKED = ("cargopolo",)

BLOCKED_WORDS = tuple(
    w.strip().lower()
    for w in (
        ",".join(DEFAULT_BLOCKED) + "," + os.environ.get("VINPRO_SCRUB_WORDS", "")
    ).split(",")
    if w.strip()
)

MASK = "[…]"

_URL = re.compile(r"\b(?:https?|ftp|ws|wss)://\S+", re.IGNORECASE)
_DOMAIN = re.compile(
    r"\b(?:[\w-]+\.)+(?:com|net|org|io|ge|ru|co|uk|dev|app|info|biz)\b", re.IGNORECASE
)
_HOST_PORT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b|\blocalhost:\d+\b")
_PATH = re.compile(r"(?:/[\w.\-]+){2,}/?")
_SELECTOR = re.compile(r"""(?:waiting for|selector|locator)\s*[:=]?\s*\S+""",
                       re.IGNORECASE)


def scrub(text: str) -> str:
    """Remove anything that identifies where the data comes from."""
    if not text:
        return ""
    out = _URL.sub(MASK, text)
    out = _DOMAIN.sub(MASK, out)
    out = _HOST_PORT.sub(MASK, out)
    out = _PATH.sub(MASK, out)
    out = _SELECTOR.sub(MASK, out)
    for word in BLOCKED_WORDS:
        out = re.sub(re.escape(word), MASK, out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).strip()


# Every message below is fixed text. None of it is built from an exception.
BUSY = (
    "სერვისი დროებით დატვირთულია. სცადეთ ხელახლა 1-2 წუთში.\n\n"
    "კრედიტი არ ჩამოგეჭრათ."
)
TIMEOUT = (
    "რეპორტის მომზადებას ჩვეულებრივზე მეტი დრო დასჭირდა. სცადეთ ხელახლა.\n\n"
    "კრედიტი არ ჩამოგეჭრათ."
)
NOT_FOUND = (
    "ამ VIN-ზე ჩანაწერი ვერ მოიძებნა. გთხოვთ გადაამოწმოთ VIN.\n\n"
    "კრედიტი არ ჩამოგეჭრათ."
)
GENERIC = (
    "ვერ მოხერხდა რეპორტის მომზადება. სცადეთ ხელახლა ან დაგვიკავშირდით.\n\n"
    "კრედიტი არ ჩამოგეჭრათ."
)

_TIMEOUT_HINTS = ("timeout", "timed out")
_BUSY_HINTS = (
    "has been closed", "target closed", "browser closed", "disconnected",
    "connection closed", "crashed", "econnrefused", "resource temporarily",
)
_NOT_FOUND_HINTS = ("no record", "not found", "404")


def classify(exc: BaseException) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, LookupError) or any(h in text for h in _NOT_FOUND_HINTS):
        return "not_found"
    if any(h in text for h in _BUSY_HINTS):
        return "busy"
    if any(h in text for h in _TIMEOUT_HINTS):
        return "timeout"
    return "generic"


def user_message(exc: BaseException) -> str:
    """The only thing that should ever be sent to a user after a failure."""
    return {
        "not_found": NOT_FOUND,
        "busy": BUSY,
        "timeout": TIMEOUT,
        "generic": GENERIC,
    }[classify(exc)]


def log_message(exc: BaseException) -> str:
    """For the log file, where detail is wanted - still scrubbed."""
    return scrub(f"{type(exc).__name__}: {exc}")
