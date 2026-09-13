"""Apply the two proven fixes to bot.py and carfax_web_api.py.

Both edits are exact string replacements. If a file does not contain the
expected text - because it was already fixed, or edited since - that edit is
skipped and reported rather than guessed at. Every changed file is backed up
first.

    python deploy/apply_fix.py --dry-run    # show what would change
    python deploy/apply_fix.py              # apply, with backups

Why these two:

1. bot.py launches Chromium with --single-process and --no-zygote. A
   single-process Chromium serves exactly ONE BrowserContext: the moment a
   second user needs one, the new context fails AND the whole browser dies,
   taking the first user's report with it. Reproduced:

       user B FAILED -> BrowserContext.new_page: Target page, context or
                        browser has been closed
       user A DIED   -> Locator.count: Target page, context or browser has
                        been closed

   The comment directly beneath those flags says they were deliberately
   removed - they were not.

2. carfax_web_api.py closes the shared CDP connection when reconnecting.
   close() on a CDP connection closes every page created through it,
   including another user's in-flight report. Reproduced in
   tests/test_shared_close_bug.py.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import difflib
import os
import re
import sys

EDITS = [
    {
        "file": "bot.py",
        "what": "remove --single-process / --no-zygote (kills the browser on a 2nd context)",
        "old": '''                "--disable-software-rasterizer",
                "--single-process",
                "--no-zygote",
                # --single-process და --no-zygote განზრახ მოხსნილია:
                # მათთან ერთი გვერდის ჩავარდნა მთელ ბრაუზერს კლავდა.
''',
        "new": '''                "--disable-software-rasterizer",
                # --single-process და --no-zygote განზრახ მოხსნილია:
                # მათთან ერთი გვერდის ჩავარდნა მთელ ბრაუზერს კლავდა.
                # (single-process Chromium მხოლოდ ერთ BrowserContext-ს უძლებს:
                #  მეორეზე მთელი ბრაუზერი კვდება და ყველა მომხმარებელი იღებს
                #  "Target page, context or browser has been closed"-ს.)
                # ქვემოთა ორი დროშა პროცესების რაოდენობას ზღუდავს, რაც
                # ანგარიშის NPROC ლიმიტისთვისაა საჭირო.
                "--renderer-process-limit=1",
                "--process-per-site",
''',
    },
    {
        "file": "carfax_web_api.py",
        "what": "stop closing the shared CDP connection (it closes other users' pages)",
        "old": '''        if _shared_browser is not None:
            try:
                await _shared_browser.close()
            except Exception:  # noqa: BLE001
                pass
            _shared_browser = None
''',
        "new": '''        if _shared_browser is not None:
            # არასდროს დავხუროთ ეს კავშირი. close() CDP კავშირზე ხურავს
            # ყველა გვერდს, რომელიც ამ კავშირით შეიქმნა — მათ შორის სხვა
            # მომხმარებლის რეპორტს, რომელიც სწორედ ახლა ირენდერება.
            # მითითების ჩამოშორება საკმარისია: ქვემოთ თავიდან დავუკავშირდებით.
            _shared_browser = None
''',
    },
]


# Message templates that must not carry the raw error. The placeholder is
# filled with Playwright's own text, which names the site being scraped.
ERROR_PLACEHOLDER_KEYS = ("report_failed",)
PLACEHOLDER = re.compile(r"\s*[:\-\u2014]?\s*\{error\}")


def fix_i18n(path: str, dry_run: bool) -> str:
    """Strip {error} from user-facing templates, in every language.

    Removing the placeholder is enough: str.format ignores an argument the
    template no longer uses, so nothing that fills it needs to change.
    """
    if not os.path.exists(path):
        return "MISSING  file not found"
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    changed = 0
    leftover = []
    for i, line in enumerate(lines):
        if any(f'"{key}"' in line or f"'{key}'" in line for key in ERROR_PLACEHOLDER_KEYS):
            if "{error}" in line:
                lines[i] = PLACEHOLDER.sub("", line)
                changed += 1
        elif "{error}" in line:
            leftover.append((i + 1, line.strip()[:90]))

    if changed == 0:
        if leftover:
            print("  no report_failed template with {error}; other templates use it:")
            for n, text in leftover:
                print(f"    line {n}: {text}")
        return "SKIP     nothing to change"

    updated = "".join(lines)
    try:
        ast.parse(updated, filename=path)
    except SyntaxError as exc:
        return f"ABORT    edit would break the file: {exc.msg}"

    with open(path, encoding="utf-8") as fh:
        original = fh.read()
    print("".join(difflib.unified_diff(
        original.splitlines(True), updated.splitlines(True),
        fromfile=path, tofile=path + " (fixed)", n=1,
    )))
    if leftover:
        print("  other templates still using {error} - review these by hand:")
        for n, text in leftover:
            print(f"    line {n}: {text}")

    if dry_run:
        return f"DRY-RUN  would fix {changed} template(s)"

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.bak-{stamp}"
    with open(backup, "w", encoding="utf-8") as fh:
        fh.write(original)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    return f"APPLIED  {changed} template(s), backup: {os.path.basename(backup)}"


def apply(path: str, edit: dict, dry_run: bool) -> str:
    if not os.path.exists(path):
        return "MISSING  file not found"
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    if edit["new"] in src and edit["old"] not in src:
        return "SKIP     already applied"
    count = src.count(edit["old"])
    if count == 0:
        return "SKIP     expected text not found (edited since?)"
    if count > 1:
        return f"SKIP     expected text appears {count} times - too ambiguous"

    updated = src.replace(edit["old"], edit["new"])
    diff = difflib.unified_diff(
        src.splitlines(True), updated.splitlines(True),
        fromfile=path, tofile=path + " (fixed)", n=2,
    )
    print("".join(diff))

    if dry_run:
        return "DRY-RUN  not written"

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.bak-{stamp}"
    with open(backup, "w", encoding="utf-8") as fh:
        fh.write(src)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    return f"APPLIED  backup: {os.path.basename(backup)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show the diff only")
    ap.add_argument("directory", nargs="?", default=".", help="bot directory")
    opts = ap.parse_args()

    results = []
    print(f"\n{'=' * 62}\ni18n.py: remove {{error}} from the message users see\n{'=' * 62}")
    results.append(("i18n.py", fix_i18n(os.path.join(opts.directory, "i18n.py"), opts.dry_run)))

    for edit in EDITS:
        path = os.path.join(opts.directory, edit["file"])
        print(f"\n{'=' * 62}\n{edit['file']}: {edit['what']}\n{'=' * 62}")
        results.append((edit["file"], apply(path, edit, opts.dry_run)))

    print(f"\n{'=' * 62}\nRESULT\n{'=' * 62}")
    for name, status in results:
        print(f"  {name:<22} {status}")

    applied = [r for r in results if r[1].startswith("APPLIED")]
    if applied:
        print("""
Restart the bot so the new browser flags take effect, then check the thread
count again - removing --single-process spreads work over more processes,
and every one counts against the account's NPROC cap:

    python deploy/measure_limits.py

To undo, move a .bak-* file back over its original.""")
    elif opts.dry_run:
        print("\nNothing written. Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
