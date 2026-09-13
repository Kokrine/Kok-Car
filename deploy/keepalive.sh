#!/usr/bin/env bash
# Restart the VIN report bot if it is not running.
# cPanel cron entry (every 5 minutes):
#     */5 * * * * /bin/bash /home/USER/vinpro-bot/deploy/keepalive.sh
#
# Adjust BOT_DIR, PYTHON and BOT_SCRIPT to match your account.

set -uo pipefail

BOT_DIR="${VINPRO_BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BOT_SCRIPT="${VINPRO_BOT_SCRIPT:-bot.py}"
PYTHON="${VINPRO_PYTHON:-python3}"
LOG="${VINPRO_LOG:-$BOT_DIR/bot.log}"
PATTERN="$BOT_DIR/$BOT_SCRIPT"

cd "$BOT_DIR" || exit 1

if pgrep -f -- "$PATTERN" >/dev/null 2>&1; then
    exit 0  # already running
fi

if [ -f "$BOT_DIR/.env.vinpro" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$BOT_DIR/.env.vinpro"
    set +a
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') keepalive: starting $BOT_SCRIPT" >> "$LOG"
nohup "$PYTHON" "$BOT_DIR/$BOT_SCRIPT" >> "$LOG" 2>&1 &
