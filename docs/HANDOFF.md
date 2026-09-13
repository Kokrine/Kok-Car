# Handoff — VIN report bot, "browser has been closed" bug

Everything a fresh session needs to continue. Nothing here requires reading
the previous conversation.

**Repository:** `Kokrine/Kok-Car`
**Working branch:** `claude/report-throwing-issue-smbnnn` (3 commits, pushed)
**Status:** fix written and tested locally; **not yet working on the server**

---

## 1. The problem

A Telegram bot ("Vinpro Carfax") takes a VIN and returns a PDF report. It
worked for the owner and failed for another user with:

```
ვერ მოხერხდა რეპორტის მიღება: Locator.count: Target page, context or browser has been closed
ვერ მოხერხდა რეპორტის მიღება: Locator.wait_for: Target page, context or browser has been closed
```

The error is Playwright's. It does not mean a bad VIN or a blocked site: it
means the browser / context / page was closed by something else while the
request was still using it. Two different call sites (`count`, `wait_for`)
failing the same way points at the browser lifecycle, not at a selector.

Likely causes, in order:

1. one global browser shared by all requests — the first request to finish
   closes it under the others;
2. Chromium killed by the host's memory limit;
3. the cPanel process manager (Passenger) recycling an idle worker mid-render;
4. Carfax allowing only one dealer session at a time.

## 2. What is in the branch

| Path | What it is |
|---|---|
| `vinpro/browser_manager.py` | The fix. One `BrowserContext` per request, semaphore-bounded concurrency, health-checked browser that relaunches when dead, retry limited to genuine "closed/crashed" errors. |
| `vinpro/telegram_example.py` | Reference handler wiring, including charging the credit only after the PDF exists. |
| `vinpro/requirements.txt` | `playwright>=1.44`, `python-telegram-bot>=20.7`. |
| `deploy/install_cpanel.sh` | Idempotent installer: fetch module, deps, Chromium, smoke test, write `.env.vinpro`. Runs the probe automatically when the browser will not start. |
| `deploy/probe_chromium.sh` / `.py` | Diagnostic: account limits, `ldd` missing-library check, then four launch configurations until one renders a page; prints the exact `.env.vinpro` lines. |
| `deploy/keepalive.sh` | Cron helper that restarts the bot when the process is gone. |
| `tests/test_browser_manager.py` | Kills the browser mid-render and checks the request still completes. |
| `docs/CPANEL_FIX.md` | Georgian, step by step, including the Chromium-will-not-start section. |
| `main.py` | Unrelated Carfax scraper, separately repaired (see §6). |

### Environment variables the manager reads

| Variable | Default | Meaning |
|---|---|---|
| `VINPRO_MAX_CONCURRENT_RENDERS` | `1` | parallel renders allowed |
| `VINPRO_FRESH_BROWSER_PER_REQUEST` | `0` | `1` = launch and close a browser per request |
| `VINPRO_NAV_TIMEOUT_MS` | `60000` | navigation/locator default timeout |
| `VINPRO_HEADLESS` | `1` | headless |
| `VINPRO_CHROMIUM_PATH` | *(empty)* | use an existing Chromium binary |
| `VINPRO_SINGLE_PROCESS` | `0` | `--single-process --no-zygote`, for LVE process limits |
| `VINPRO_LOW_MEMORY` | `0` | extra RAM-saving flags |
| `VINPRO_CHROMIUM_ARGS` | *(empty)* | extra flags, space separated |

## 3. What is verified, and what is not

**Verified** — `tests/test_browser_manager.py` run against real Chromium,
passing in every supported mode (shared browser, fresh-browser-per-request,
single-process). It covers: five concurrent renders; a browser dropped
mid-locator, which reproduces `Locator.count: Target page, context or
browser has been closed` and then recovers; a genuine timeout that must
still surface rather than be retried away; clean shutdown.

A trap found while testing: `--single-process` Chromium serves **exactly one
BrowserContext**. Opening a second kills it with the very error being fixed.
Setting `VINPRO_SINGLE_PROCESS=1` therefore forces
`VINPRO_FRESH_BROWSER_PER_REQUEST=1` and `VINPRO_MAX_CONCURRENT_RENDERS=1`
and logs that it did. Do not remove that guard.

**Not verified** — anything on the actual server. The fix has never run
there, because Chromium does not start yet (§5).

## 4. Server facts (from the user's terminal output)

* cPanel account `mycarge`, host `s13612`, home `/home/mycarge`.
* Python found by the installer: `/bin/python`, **3.9.25**, with **no
  virtualenv active** — `pip` fell back to `~/.local/lib/python3.9/`.
* Already installed there: `playwright 1.60.0`, `python-telegram-bot 22.5`.
* `playwright install chromium` succeeded, with
  `your OS is not officially supported ... fallback build for ubuntu24.04-x64`.
* The smoke test failed: Chromium exits immediately,
  `process did exit: exitCode=null, signal=SIGTRAP`.
* The bot's own source has **never been seen** — not in this repo, not shared.

## 5. Open items, in order

1. **Locate the bot's directory.** The installer was run from `/home/mycarge`
   because `cd ~/vinpro-bot` failed, so `vinpro/` landed in
   `/home/mycarge/vinpro/`, where the bot cannot import it. Find the real
   directory, delete the stray copy, re-run the installer from there:
   ```bash
   grep -rl --include='*.py' -e telegram -e playwright ~ 2>/dev/null | head
   ```
2. **Get Chromium to start.** Run `bash deploy/probe_chromium.sh` in the bot
   directory and read its output. The `ldd` section is the decisive part: if
   libraries are missing, they cannot be installed without root on shared
   hosting — the host must install them, or the bot moves to a VPS. If the
   probe finds a working configuration, copy its lines into `.env.vinpro`.
3. **Edit the handler.** Nobody has done this yet and the installer cannot:
   remove every `chromium.launch()` / `browser.close()` from the VIN handler
   and call `render_with_retry(build_report, vin)` instead. Model it on
   `vinpro/telegram_example.py`.
4. **Take the bot out of Passenger.** Under "Setup Python App" idle workers
   are recycled and take Chromium down mid-render — the same error again,
   independent of the code. Run it as a plain process kept alive by cron:
   ```
   */5 * * * * /bin/bash /home/mycarge/<botdir>/deploy/keepalive.sh
   ```
5. **Test the real scenario:** two VINs at once from two different accounts.

## 6. Notes carried from the session

* `main.py` (the Carfax listings scraper, unrelated to the bot) could not be
  parsed at all — a broken authorization header on line 43. Repaired, along
  with credentials moved to environment variables, a `todays_date` NameError,
  unhandled non-JSON responses, an empty-result crash, and missing timeouts.
  `requirements.txt` was unpinned (`pandas==1.0.2` does not build on modern
  Python) and `openpyxl` added.
* **Security:** the old `main.py` had a Carfax dealer JWT and a full cookie
  header committed in plain text, and they remain in git history. Both are
  expired, but if that account is still in use its credentials should be
  rotated.
* Claude sessions have **no access** to the user's cPanel, SSH, desktop, or
  Chrome. The only channel is: the user runs a command and pastes the output
  back. Do not offer to "log in" or "take control" — say what to run.
* The user writes in Georgian; answer in Georgian.
