#!/usr/bin/env bash
# VIN report bot - one-shot installer for cPanel hosting.
#
# Run it from the directory that holds the bot (the one with bot.py / main.py):
#
#     cd ~/vinpro-bot
#     bash install_cpanel.sh
#
# It is idempotent: re-running only fixes what is missing.

set -uo pipefail

BRANCH="${VINPRO_BRANCH:-claude/report-throwing-issue-smbnnn}"
REPO="${VINPRO_REPO:-https://github.com/Kokrine/Kok-Car}"
BOT_DIR="$(pwd)"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

FAILED=0
note_fail() { red "    FAILED: $*"; FAILED=1; }

step "1/6  Python"
PY=""
for candidate in "${VIRTUAL_ENV:-}/bin/python" python3.11 python3.10 python3.9 python3 python; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1; then PY="$(command -v "$candidate")"; break; fi
done
if [ -z "$PY" ]; then
    red "No Python interpreter found."
    red "In cPanel open 'Setup Python App', note the virtualenv activation"
    red "command it shows, run it, then re-run this script."
    exit 1
fi
green "    using $PY ($("$PY" -V 2>&1))"
if [ -z "${VIRTUAL_ENV:-}" ]; then
    yellow "    WARNING: no virtualenv active. On cPanel you normally run the"
    yellow "    'source /home/USER/virtualenv/<app>/<ver>/bin/activate' command"
    yellow "    from Setup Python App first, otherwise pip installs may be lost."
fi

step "1b/6  Bot directory"
BOT_SCRIPT_FOUND=""
for f in bot.py main.py app.py run.py vinpro_bot.py; do
    [ -f "$BOT_DIR/$f" ] && BOT_SCRIPT_FOUND="$f" && break
done
if [ -n "$BOT_SCRIPT_FOUND" ]; then
    green "    found $BOT_DIR/$BOT_SCRIPT_FOUND"
else
    yellow "    No bot script found in $BOT_DIR."
    yellow "    You are probably not in the bot's directory - vinpro/ must sit"
    yellow "    NEXT TO the file that starts the bot, or Python will not import it."
    yellow "    Find it with:"
    yellow "      grep -rl --include='*.py' -e telegram -e playwright ~ 2>/dev/null | head"
    yellow "    then cd there and re-run this script."
fi

step "2/6  Fetching vinpro/ module"
if [ -d "$BOT_DIR/vinpro" ] && [ -f "$BOT_DIR/vinpro/browser_manager.py" ]; then
    green "    vinpro/ already present - refreshing"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if command -v git >/dev/null 2>&1 && git clone --depth 1 --branch "$BRANCH" "$REPO" "$TMP/repo" >/dev/null 2>&1; then
    green "    cloned $BRANCH"
elif command -v curl >/dev/null 2>&1; then
    yellow "    git unavailable or clone failed - trying tarball download"
    if curl -fsSL "$REPO/archive/refs/heads/$BRANCH.tar.gz" -o "$TMP/src.tar.gz" \
       && mkdir -p "$TMP/repo" \
       && tar -xzf "$TMP/src.tar.gz" -C "$TMP/repo" --strip-components=1; then
        green "    downloaded $BRANCH"
    else
        note_fail "could not download the module. Upload the vinpro/ folder"
        red "    manually via cPanel File Manager, then re-run this script."
    fi
else
    note_fail "neither git nor curl is available"
fi
if [ -d "$TMP/repo/vinpro" ]; then
    cp -r "$TMP/repo/vinpro" "$BOT_DIR/"
    mkdir -p "$BOT_DIR/deploy"
    for f in keepalive.sh probe_chromium.sh probe_chromium.py; do
        [ -f "$TMP/repo/deploy/$f" ] && cp "$TMP/repo/deploy/$f" "$BOT_DIR/deploy/"
    done
    chmod +x "$BOT_DIR"/deploy/*.sh 2>/dev/null
    green "    installed $BOT_DIR/vinpro/"
elif [ ! -f "$BOT_DIR/vinpro/browser_manager.py" ]; then
    note_fail "vinpro/ is missing and could not be fetched"
fi

step "3/6  Python dependencies"
"$PY" -m pip install --upgrade pip >/dev/null 2>&1
if "$PY" -m pip install "playwright>=1.44" "python-telegram-bot>=20.7"; then
    green "    playwright + python-telegram-bot installed"
else
    note_fail "pip install failed (check the disk quota and memory limit)"
fi

step "4/6  Chromium"
CHROMIUM_PATH=""
if "$PY" -m playwright install chromium; then
    green "    chromium installed"
else
    yellow "    playwright install failed - looking for a system Chromium"
    for candidate in \
        "$(command -v chromium-browser 2>/dev/null)" \
        "$(command -v chromium 2>/dev/null)" \
        "$(command -v google-chrome 2>/dev/null)" \
        /usr/lib/chromium/chromium \
        /usr/bin/chromium-browser \
        /opt/google/chrome/chrome
    do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then CHROMIUM_PATH="$candidate"; break; fi
    done
    if [ -n "$CHROMIUM_PATH" ]; then
        green "    using system Chromium at $CHROMIUM_PATH"
    else
        note_fail "no Chromium available"
        yellow "    Ask your host to allow the playwright download, or install"
        yellow "    Chromium and set VINPRO_CHROMIUM_PATH to its full path."
    fi
fi
export VINPRO_CHROMIUM_PATH="$CHROMIUM_PATH"

step "5/6  Smoke test"
SMOKE_OUT="$("$PY" - <<'PYEOF' 2>&1
import asyncio, sys

try:
    from vinpro.browser_manager import manager
except Exception as exc:
    print(f"IMPORT-FAIL {exc}")
    sys.exit(1)


async def main():
    try:
        async with manager.page() as page:
            await page.set_content("<h1 id='ok'>ready</h1>")
            await page.locator("#ok").wait_for(state="visible", timeout=15_000)
            assert await page.locator("#ok").count() == 1
        await manager.shutdown()
    except Exception as exc:
        print(f"RUN-FAIL {type(exc).__name__}: {exc}")
        sys.exit(1)
    print("SMOKE-OK")


asyncio.run(main())
PYEOF
)"
SMOKE_LOG="$BOT_DIR/vinpro_smoke.log"
printf '%s\n' "$SMOKE_OUT" > "$SMOKE_LOG"
if printf '%s' "$SMOKE_OUT" | grep -q SMOKE-OK; then
    green "    browser launches and locators work"
else
    note_fail "smoke test did not pass"
    yellow "    full output saved to $SMOKE_LOG"
    printf '%s\n' "$SMOKE_OUT" | grep -vE '^\s*-? *\[pid=' | tail -30 | sed 's/^/    /'
    step "5b/6  Chromium will not start - running the diagnostic probe"
    yellow "    (this tries several launch configurations; it takes a minute)"
    if [ -f "$BOT_DIR/deploy/probe_chromium.sh" ]; then
        PROBE_LOG="$BOT_DIR/vinpro_probe.log"
        VINPRO_PYTHON="$PY" bash "$BOT_DIR/deploy/probe_chromium.sh" 2>&1 | tee "$PROBE_LOG" | grep -vE '^\s*-? *\[pid='
        yellow "    full probe output saved to $PROBE_LOG"
        if grep -q "Working configuration" "$PROBE_LOG" 2>/dev/null; then
            green "    a working configuration was found - see the block above"
            green "    and copy those lines into $BOT_DIR/.env.vinpro"
            FAILED=0
        fi
    else
        yellow "    probe script missing - run deploy/probe_chromium.sh by hand"
    fi
fi

step "6/6  Environment"
ENV_FILE="$BOT_DIR/.env.vinpro"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'ENVEOF'
# Source this before starting the bot:  set -a; . ./.env.vinpro; set +a
VINPRO_MAX_CONCURRENT_RENDERS=1
VINPRO_FRESH_BROWSER_PER_REQUEST=0
VINPRO_NAV_TIMEOUT_MS=60000
VINPRO_HEADLESS=1
ENVEOF
    if [ -n "$CHROMIUM_PATH" ]; then
        echo "VINPRO_CHROMIUM_PATH=$CHROMIUM_PATH" >> "$ENV_FILE"
    fi
    green "    wrote $ENV_FILE"
else
    green "    $ENV_FILE already exists - left untouched"
fi

MEM_KB="$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null)"
if [ -n "$MEM_KB" ] && [ "$MEM_KB" -lt 1500000 ]; then
    yellow "    Only $((MEM_KB / 1024)) MB RAM visible. Chromium is heavy -"
    yellow "    set VINPRO_FRESH_BROWSER_PER_REQUEST=1 in $ENV_FILE."
fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then
    green "=== Install finished. ==="
else
    red "=== Install finished WITH ERRORS - see the FAILED lines above. ==="
fi

cat <<'NEXTEOF'

Still to do by hand (the installer cannot edit your handler for you):

  1. In the bot's VIN handler, delete every chromium.launch() and
     browser.close() and use instead:

         from vinpro.browser_manager import render_with_retry

         async def build_report(page, vin):
             await page.goto(f"https://.../{vin}", wait_until="domcontentloaded")
             await page.locator("#report").wait_for(state="visible", timeout=60_000)
             return await page.pdf(format="A4")

         pdf_bytes = await render_with_retry(build_report, vin)

     A full working handler is in vinpro/telegram_example.py.

  2. Keep the bot running as a plain process, NOT under Passenger -
     Passenger recycles idle workers and kills Chromium mid-render, which
     is the same error again. Add this cron job (cPanel -> Cron Jobs,
     every 5 minutes), adjusting the paths:

         */5 * * * * /bin/bash /home/USER/vinpro-bot/deploy/keepalive.sh

  3. Test with two VINs at once from two different accounts - that is the
     case that used to break.

NEXTEOF
exit "$FAILED"
