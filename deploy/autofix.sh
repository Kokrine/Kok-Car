#!/usr/bin/env bash
# One command that does every automatable step of the browser-lifecycle fix.
#
#     bash autofix.sh
#
# It finds the bot's directory itself, installs the vinpro module next to it,
# installs the dependencies into the interpreter the bot actually uses, gets
# Chromium working (probing launch configurations when it will not start),
# writes .env.vinpro, and reports the exact lines of the bot that still need
# a human edit.
#
# Nothing is started, stopped, or overwritten without saying so. The two
# steps it deliberately leaves to you are the handler edit (it cannot rewrite
# code it has not been asked about) and the cron job (see the end).
#
# Overrides:
#     VINPRO_BOT_DIR=/path/to/bot   skip auto-discovery
#     VINPRO_PYTHON=/path/to/python skip interpreter detection

set -uo pipefail

BRANCH="${VINPRO_BRANCH:-claude/report-throwing-issue-smbnnn}"
REPO="${VINPRO_REPO:-https://github.com/Kokrine/Kok-Car}"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

FAILED=0
TODO=()
note_fail() { red "    FAILED: $*"; FAILED=1; }
todo() { TODO+=("$1"); }

# ---------------------------------------------------------------- 1. bot dir
step "1/8  Locating the bot"
BOT_DIR="${VINPRO_BOT_DIR:-}"
if [ -z "$BOT_DIR" ]; then
    yellow "    searching $HOME for a Playwright + Telegram bot..."
    CANDIDATES="$(grep -rl --include='*.py' -e 'playwright' "$HOME" 2>/dev/null \
        | grep -v -e site-packages -e /\\.cache/ -e /vinpro/ -e node_modules \
        | head -50)"
    BEST=""
    for f in $CANDIDATES; do
        if grep -q -e telegram -e 'Update' "$f" 2>/dev/null; then BEST="$f"; break; fi
    done
    [ -z "$BEST" ] && BEST="$(printf '%s\n' "$CANDIDATES" | head -1)"
    [ -n "$BEST" ] && BOT_DIR="$(cd "$(dirname "$BEST")" && pwd)"
fi
if [ -z "$BOT_DIR" ] || [ ! -d "$BOT_DIR" ]; then
    red "    Could not find the bot automatically."
    red "    Run this to look yourself, then re-run with the directory:"
    red "      grep -rl --include='*.py' -e telegram -e playwright ~ | head"
    red "      VINPRO_BOT_DIR=/home/$USER/<dir> bash autofix.sh"
    exit 1
fi
green "    bot directory: $BOT_DIR"
[ -f "$BOT_DIR/passenger_wsgi.py" ] && \
    yellow "    passenger_wsgi.py found - the bot runs under Passenger (see step 8)"

# --------------------------------------------------------------- 2. cleanup
step "2/8  Cleaning up misplaced copies"
CLEANED=0
for stray in "$HOME/vinpro"; do
    if [ -d "$stray" ] && [ "$stray" != "$BOT_DIR/vinpro" ]; then
        rm -rf "$stray" && green "    removed stray copy at $stray" && CLEANED=1
    fi
done
[ "$CLEANED" -eq 0 ] && green "    nothing to clean up"

# ---------------------------------------------------------------- 3. python
step "3/8  Python interpreter"
PY="${VINPRO_PYTHON:-}"
if [ -z "$PY" ]; then
    # Prefer an interpreter that already has playwright: that is the one the
    # bot itself runs under.
    for candidate in "${VIRTUAL_ENV:-}/bin/python" \
                     "$HOME"/virtualenv/*/*/bin/python \
                     python3 python; do
        [ -n "$candidate" ] || continue
        command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ] || continue
        if "$candidate" -c "import playwright" >/dev/null 2>&1; then
            PY="$candidate"; break
        fi
        [ -z "$PY" ] && PY="$candidate"
    done
fi
[ -z "$PY" ] && { red "    No Python found."; exit 1; }
green "    $PY  ($("$PY" -V 2>&1))"
if "$PY" -c "import playwright" >/dev/null 2>&1; then
    green "    playwright already importable here"
else
    yellow "    playwright not importable yet - installing in step 5"
fi

# ---------------------------------------------------------------- 4. module
step "4/8  Installing the vinpro module"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FETCHED=0
if command -v git >/dev/null 2>&1 && \
   git clone --depth 1 --branch "$BRANCH" "$REPO" "$TMP/repo" >/dev/null 2>&1; then
    FETCHED=1
elif command -v curl >/dev/null 2>&1 && \
     curl -fsSL "$REPO/archive/refs/heads/$BRANCH.tar.gz" -o "$TMP/s.tgz" && \
     mkdir -p "$TMP/repo" && tar -xzf "$TMP/s.tgz" -C "$TMP/repo" --strip-components=1; then
    FETCHED=1
fi
if [ "$FETCHED" -eq 1 ]; then
    cp -r "$TMP/repo/vinpro" "$BOT_DIR/"
    mkdir -p "$BOT_DIR/deploy"
    cp "$TMP/repo"/deploy/*.sh "$TMP/repo"/deploy/*.py "$BOT_DIR/deploy/" 2>/dev/null
    chmod +x "$BOT_DIR"/deploy/*.sh 2>/dev/null
    green "    installed $BOT_DIR/vinpro/"
else
    note_fail "could not download the module - upload vinpro/ by hand"
fi

# ------------------------------------------------------------------ 5. deps
step "5/8  Dependencies"
if "$PY" -m pip install --quiet --upgrade "playwright>=1.44" "python-telegram-bot>=20.7"; then
    green "    playwright + python-telegram-bot ready"
else
    note_fail "pip install failed (disk quota or memory limit?)"
fi

# -------------------------------------------------------------- 6. chromium
step "6/8  Chromium"
CHROMIUM_ENV=""
"$PY" -m playwright install chromium >/dev/null 2>&1 && green "    chromium installed" \
    || yellow "    playwright install did not succeed - the probe will look for alternatives"

SMOKE="$(cd "$BOT_DIR" && PYTHONPATH="$BOT_DIR" "$PY" - <<'PYEOF' 2>&1
import asyncio, sys
try:
    from vinpro.browser_manager import manager
except Exception as exc:
    print(f"IMPORT-FAIL {exc}"); sys.exit(1)
async def main():
    try:
        async with manager.page() as page:
            await page.set_content("<h1 id='ok'>ready</h1>")
            await page.locator("#ok").wait_for(state="visible", timeout=15_000)
            assert await page.locator("#ok").count() == 1
        await manager.shutdown()
    except Exception as exc:
        print(f"RUN-FAIL {type(exc).__name__}: {exc}"); sys.exit(1)
    print("SMOKE-OK")
asyncio.run(main())
PYEOF
)"
printf '%s\n' "$SMOKE" > "$BOT_DIR/vinpro_smoke.log"
if printf '%s' "$SMOKE" | grep -q SMOKE-OK; then
    green "    browser launches and locators work"
else
    yellow "    browser did not start - probing launch configurations"
    printf '%s\n' "$SMOKE" | grep -vE '^\s*-? *\[pid=' | tail -15 | sed 's/^/      /'
    PROBE_LOG="$BOT_DIR/vinpro_probe.log"
    (cd "$BOT_DIR" && VINPRO_PYTHON="$PY" bash deploy/probe_chromium.sh) \
        > "$PROBE_LOG" 2>&1
    grep -vE '^\s*-? *\[pid=' "$PROBE_LOG" | tail -40 | sed 's/^/      /'
    if grep -q "Working configuration" "$PROBE_LOG"; then
        CHROMIUM_ENV="$(sed -n '/Add these lines/,/^====/p' "$PROBE_LOG" \
            | grep -E '^\s+VINPRO_' | sed 's/^[[:space:]]*//')"
        green "    found a working configuration"
    else
        note_fail "Chromium will not start in any configuration"
        todo "Chromium cannot run on this host. Check $PROBE_LOG - if it lists
      missing libraries, only the hosting provider can install them.
      Otherwise the bot needs a VPS."
    fi
fi

# ------------------------------------------------------------------- 7. env
step "7/8  Writing .env.vinpro"
ENV_FILE="$BOT_DIR/.env.vinpro"
{
    echo "# written by autofix.sh on $(date '+%Y-%m-%d %H:%M')"
    echo "VINPRO_MAX_CONCURRENT_RENDERS=1"
    echo "VINPRO_NAV_TIMEOUT_MS=60000"
    echo "VINPRO_HEADLESS=1"
    MEM_KB="$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null)"
    if [ -n "$MEM_KB" ] && [ "$MEM_KB" -lt 1500000 ]; then
        echo "VINPRO_FRESH_BROWSER_PER_REQUEST=1   # low memory host"
    else
        echo "VINPRO_FRESH_BROWSER_PER_REQUEST=0"
    fi
    [ -n "$CHROMIUM_ENV" ] && printf '%s\n' "$CHROMIUM_ENV"
} > "$ENV_FILE"
green "    $ENV_FILE"
sed 's/^/      /' "$ENV_FILE"

# -------------------------------------------------------------- 8. analysis
step "8/8  What still needs a human"
if [ -f "$BOT_DIR/deploy/analyze_bot.py" ]; then
    ANALYSIS="$("$PY" "$BOT_DIR/deploy/analyze_bot.py" "$BOT_DIR" 2>&1)"
    printf '%s\n' "$ANALYSIS" | sed 's/^/    /'
    if printf '%s' "$ANALYSIS" | grep -qE 'place\(s\) to change'; then
        todo "Edit the handler at the lines listed above. The analyzer found the
      launch/close calls; replace them with render_with_retry(). Full
      example in vinpro/telegram_example.py."
    fi
else
    yellow "    analyzer missing - skipped"
fi

if [ -f "$BOT_DIR/passenger_wsgi.py" ]; then
    todo "The bot runs under Passenger, which recycles idle workers and kills
      Chromium mid-render - the same error, whatever the code does. Run it
      as a plain process instead, kept alive by this cron entry:
        */5 * * * * /bin/bash $BOT_DIR/deploy/keepalive.sh
      Not installed automatically: if the old bot keeps running too, both
      poll Telegram at once and neither works."
else
    todo "Keep the bot alive with cron (add in cPanel -> Cron Jobs):
        */5 * * * * /bin/bash $BOT_DIR/deploy/keepalive.sh
      Not installed automatically, so it cannot collide with however the
      bot is started today."
fi

printf '\n\033[1m%s\033[0m\n' "================ SUMMARY ================"
if [ "$FAILED" -eq 0 ]; then
    green "Automated steps completed."
else
    red "Some automated steps failed - see the FAILED lines above."
fi
if [ "${#TODO[@]}" -gt 0 ]; then
    printf '\n\033[1mLeft for you:\033[0m\n'
    i=1
    for t in "${TODO[@]}"; do
        printf '  %d. %s\n' "$i" "$t"
        i=$((i + 1))
    done
fi
printf '\nLogs: %s\n' "$BOT_DIR/vinpro_smoke.log"
[ -f "$BOT_DIR/vinpro_probe.log" ] && printf '       %s\n' "$BOT_DIR/vinpro_probe.log"
exit "$FAILED"
