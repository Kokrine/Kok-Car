"""Collect everything needed to diagnose the bot, with secrets removed.

Chromium will not start and the handler needs editing, but the code cannot
be read from here. This gathers the relevant pieces into one file that is
safe to paste: host limits, the Chromium libraries check, and the code
around each place the analyzer flagged - with tokens, passwords and cookies
masked out.

    python deploy/collect_context.py            # writes ~/vinpro_context.txt
    python deploy/collect_context.py -o out.txt

Read the output before sending it. Redaction is careful but never perfect.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

CONTEXT_LINES = 22

SECRET_WORDS = (
    "token", "secret", "password", "passwd", "api_key", "apikey", "auth",
    "cookie", "credential", "bearer", "session", "private_key", "webhook",
)
# A quoted run long enough to be a credential rather than a message.
LONG_LITERAL = re.compile(r"""(['"])([A-Za-z0-9_\-\.:/+=]{28,})\1""")
ASSIGNMENT = re.compile(r"""^(\s*[\w\.\[\]'"]*\s*[:=]\s*)(.+)$""")


# Credential-bearing query parameters inside an otherwise harmless URL.
URL_CREDENTIAL = re.compile(
    r"(?i)([?&](?:token|key|auth|password|sig|signature|session|secret)[^=&]*=)[^&]+"
)


def _redact_literal(match: re.Match) -> str:
    quote, value = match.group(1), match.group(2)
    # URLs and paths stay readable - which page the bot opens matters for
    # diagnosis - but credentials carried in the query string do not.
    if value.startswith(("http://", "https://", "/", "./", "../")):
        # Computed outside the f-string: Python 3.9 rejects a backslash there.
        cleaned = URL_CREDENTIAL.sub(r"\1***REDACTED***", value)
        return quote + cleaned + quote
    return f"{quote}***REDACTED***{quote}"


def redact(line: str) -> str:
    lowered = line.lower()
    if any(word in lowered for word in SECRET_WORDS):
        m = ASSIGNMENT.match(line)
        if m and m.group(2).strip() not in ("{", "[", "("):
            return f"{m.group(1)}***REDACTED***"
    return LONG_LITERAL.sub(_redact_literal, line)


def run(cmd: list[str] | str, shell: bool = False) -> str:
    try:
        out = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=60
        )
        return (out.stdout + out.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return f"(failed: {exc})"


def section(fh, title: str) -> None:
    fh.write(f"\n{'=' * 62}\n{title}\n{'=' * 62}\n")


def collect_host(fh) -> None:
    section(fh, "HOST")
    fh.write(f"python   : {sys.version.split()[0]} at {sys.executable}\n")
    fh.write(f"uname    : {run(['uname', '-a'])}\n")
    for path, label in (("/proc/meminfo", "MemTotal"),):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith(label):
                        fh.write(f"memory   : {line.strip()}\n")
                        break
        except OSError:
            pass
    fh.write(f"ulimits  : {run('ulimit -u -n -v 2>/dev/null', shell=True)}\n")
    fh.write(f"shm      : {run('df -h /dev/shm 2>/dev/null | tail -1', shell=True)}\n")
    fh.write(f"playwright: {run([sys.executable, '-m', 'playwright', '--version'])}\n")


def collect_chromium(fh) -> None:
    section(fh, "CHROMIUM  (the decisive part)")
    roots = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        os.path.expanduser("~/.cache/ms-playwright"),
    ]
    binaries: list[str] = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for pattern in ("*/chrome-linux*/chrome", "*/chrome-linux*/headless_shell",
                        "*/chrome-headless-shell-linux*/chrome-headless-shell"):
            binaries.extend(glob.glob(os.path.join(root, pattern)))
    binaries = sorted(set(binaries))
    if not binaries:
        fh.write("no Chromium binary found\n")
        return
    for binary in binaries:
        fh.write(f"\n--- {binary}\n")
        fh.write(f"    size: {os.path.getsize(binary) // (1024 * 1024)} MB, "
                 f"executable: {os.access(binary, os.X_OK)}\n")
        ldd = run(["ldd", binary])
        missing = [l.strip() for l in ldd.splitlines() if "not found" in l]
        if missing:
            fh.write("    MISSING LIBRARIES:\n")
            for line in missing:
                fh.write(f"      {line}\n")
        else:
            fh.write("    all libraries resolved\n")
        # What the kernel says when it is run directly, which is often
        # clearer than what Playwright reports.
        direct = run([binary, "--headless", "--version"])
        fh.write(f"    direct run: {direct[:400] or '(no output)'}\n")


def collect_code(fh, bot_dir: str) -> None:
    section(fh, "CODE AROUND EACH FINDING  (secrets masked)")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import analyze_bot
    except Exception as exc:  # noqa: BLE001
        fh.write(f"analyzer unavailable: {exc}\n")
        return

    reports = analyze_bot.walk(bot_dir)
    if not reports:
        fh.write(f"no Playwright code found under {bot_dir}\n")
        return

    for rep in sorted(reports, key=lambda r: r.path):
        lines_of_interest = sorted(
            {f.line for f in rep.findings if f.kind in ("LAUNCH", "CLOSE", "SYNTAX")}
            | set(rep.global_browser)
        )
        if not lines_of_interest:
            continue
        try:
            with open(rep.path, encoding="utf-8", errors="replace") as f:
                src = f.readlines()
        except OSError as exc:
            fh.write(f"\n--- {rep.path}: cannot read ({exc})\n")
            continue

        fh.write(f"\n--- {rep.path}  ({len(src)} lines)\n")
        # Merge overlapping windows so nothing is printed twice.
        windows: list[list[int]] = []
        for line in lines_of_interest:
            lo = max(1, line - CONTEXT_LINES // 2)
            hi = min(len(src), line + CONTEXT_LINES // 2)
            if windows and lo <= windows[-1][1] + 3:
                windows[-1][1] = max(windows[-1][1], hi)
            else:
                windows.append([lo, hi])
        for lo, hi in windows:
            fh.write(f"\n  ... lines {lo}-{hi} ...\n")
            for n in range(lo, hi + 1):
                fh.write(f"  {n:>5}| {redact(src[n - 1].rstrip())}\n")


def main() -> int:
    out_path = os.path.expanduser("~/vinpro_context.txt")
    args = sys.argv[1:]
    if "-o" in args:
        out_path = args[args.index("-o") + 1]
        args = [a for i, a in enumerate(args) if i not in
                (args.index("-o"), args.index("-o") + 1)]
    bot_dir = args[0] if args else os.path.dirname(os.path.abspath(__file__)) + "/.."
    bot_dir = os.path.abspath(bot_dir)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("VIN bot diagnostic context\n")
        fh.write(f"bot directory: {bot_dir}\n")
        collect_host(fh)
        collect_chromium(fh)
        collect_code(fh, bot_dir)

    size = os.path.getsize(out_path)
    print(f"Written: {out_path}  ({size // 1024} KB)")
    print()
    print("Secrets were masked, but CHECK THE FILE BEFORE SENDING IT:")
    print(f"    less {out_path}")
    print("Then paste its contents back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
