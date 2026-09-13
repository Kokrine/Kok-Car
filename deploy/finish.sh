#!/usr/bin/env bash
# Everything left, in one command. Run it in the bot's directory:
#
#     cd ~/telegram-carfax-bot-new && bash finish.sh
#
# 1. fetches the current tools
# 2. shows what would change, then applies it (with backups)
# 3. re-analyses the code for anything still leaking errors to users
# 4. reports the account's process usage
# 5. prints exactly how to restart, based on what is running now

set -uo pipefail

RAW="https://raw.githubusercontent.com/Kokrine/Kok-Car/claude/report-throwing-issue-smbnnn/deploy"
BOT_DIR="${VINPRO_BOT_DIR:-$(pwd)}"
PY="${VINPRO_PYTHON:-$(command -v python3 || command -v python)}"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

cd "$BOT_DIR" || { red "cannot enter $BOT_DIR"; exit 1; }
if [ ! -f bot.py ]; then
    red "No bot.py here ($BOT_DIR)."
    red "cd into the bot's directory first, e.g.:  cd ~/telegram-carfax-bot-new"
    exit 1
fi
mkdir -p deploy

step "1/5  Fetching the tools"
for f in apply_fix.py analyze_bot.py measure_limits.py; do
    if curl -fsSL -o "deploy/$f" "$RAW/$f"; then
        green "    deploy/$f"
    else
        red "    could not download $f"
    fi
done

step "2/5  What will change"
"$PY" deploy/apply_fix.py --dry-run . 2>&1 | sed 's/^/    /'

step "3/5  Applying (originals are backed up)"
"$PY" deploy/apply_fix.py . 2>&1 | tail -20 | sed 's/^/    /'

step "4/5  Anything still showing raw errors to users"
"$PY" deploy/analyze_bot.py . 2>&1 | sed 's/^/    /'

step "5/5  Account process usage"
"$PY" deploy/measure_limits.py 2>&1 | sed -n '1,12p' | sed 's/^/    /'

step "Restart"
echo "    Running now:"
ps -o pid=,cmd= -u "$(id -un)" 2>/dev/null \
    | grep -E 'python[0-9.]* (bot|carfax_web_api|app|worker)\.py' \
    | grep -v grep | sed 's/^/      /'
cat <<'EOF'

    The browser flags only take effect on a fresh start, so bot.py must be
    restarted - and carfax_web_api.py with it, since it attaches to the
    browser bot.py owns. Restart them the same way you normally start them.
    If that is plain nohup, it looks like:

      kill <bot.py pid> <carfax_web_api.py pid>
      nohup python3 bot.py >> bot.log 2>&1 &
      nohup python3 carfax_web_api.py >> web_api.log 2>&1 &

    Then send two VINs at once from two different accounts - the case that
    used to break - and check the thread count again:

      python3 deploy/measure_limits.py
EOF
