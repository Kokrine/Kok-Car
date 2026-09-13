#!/usr/bin/env bash
# Diagnose why Chromium will not start on this host.
#
#     bash deploy/probe_chromium.sh
#
# Prints the account's limits, checks the Chromium binary for missing shared
# libraries, then probes launch configurations until one works.

set -uo pipefail

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

PY="${VINPRO_PYTHON:-$(command -v python3 || command -v python)}"

step "Account limits"
echo "    max user processes : $(ulimit -u 2>/dev/null)"
echo "    max open files     : $(ulimit -n 2>/dev/null)"
echo "    virtual memory      : $(ulimit -v 2>/dev/null)"
MEM_KB="$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null)"
[ -n "$MEM_KB" ] && echo "    MemTotal            : $((MEM_KB / 1024)) MB"
SHM="$(df -k /dev/shm 2>/dev/null | awk 'NR==2{print $2}')"
[ -n "$SHM" ] && echo "    /dev/shm            : $((SHM / 1024)) MB"
if [ -n "${MEM_KB:-}" ] && [ "$MEM_KB" -lt 1000000 ]; then
    yellow "    Chromium wants ~500 MB per instance - this is tight."
fi

step "Locating the Chromium binary"
CHROME=""
if [ -n "${VINPRO_CHROMIUM_PATH:-}" ] && [ -x "${VINPRO_CHROMIUM_PATH}" ]; then
    CHROME="$VINPRO_CHROMIUM_PATH"
else
    CHROME="$(find "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
        -maxdepth 4 \( -name chrome -o -name headless_shell -o -name chrome-headless-shell \) \
        -type f -perm -u+x 2>/dev/null | head -1)"
fi
if [ -z "$CHROME" ]; then
    red "    No Chromium binary found."
    red "    Run:  $PY -m playwright install chromium"
    exit 1
fi
green "    $CHROME"

step "Shared library check (ldd)"
if command -v ldd >/dev/null 2>&1; then
    MISSING="$(ldd "$CHROME" 2>/dev/null | grep 'not found' | awk '{print $1}' | sort -u)"
    if [ -n "$MISSING" ]; then
        red "    Missing libraries:"
        echo "$MISSING" | sed 's/^/      /'
        yellow "    On shared hosting you cannot install these yourself."
        yellow "    Send this list to the host and ask them to install the"
        yellow "    packages, or run the bot on a VPS instead."
    else
        green "    all libraries resolved"
    fi
else
    yellow "    ldd unavailable - skipping"
fi

step "Probing launch configurations"
export VINPRO_CHROMIUM_PATH="$CHROME"
cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null || true
PYTHONPATH="${PYTHONPATH:-.}" "$PY" deploy/probe_chromium.py
