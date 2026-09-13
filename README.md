# Disclaimer

* I do not promote, encourage, support or excite any illegal activity or hacking without written permission in general. The repo and author of the repo is no way responsible for any misuse of the information.

* "carfax-scraper" is just a terms that represents the name of the repo and is not a repo that provides any illegal information.

* The Software's and Scripts provided by the repo should only be used for **_EDUCATIONAL PURPOSES ONLY_**. The repo or the author can not be held responsible for the misuse of them by the users.

* I am not responsible for any direct or indirect damage caused due to the usage of the code provided on this site. All the information provided on this repo are for educational purposes only.



## Usage Instructions 

(Google Chrome only; only tested on Mac OS) 



1. Copy repo:
   
`git clone https://github.com/grsahagian/carfax-scraper`


2. Install dependencies (requirements.txt)
   
#### Get Authorization code
3. Navigate to https://www.carfax.com/cars-for-sale
3. Search for any car model, make within any valid zip code then click "Show me results.
4. Right click anywhere on the page and select "Inspect"
5. Click "Network" on the top of the new window then click "Search" again
6. On the left side under "Name" click on the row labelled "findVehicles?tpQualityThreshold=150..."
7. Scroll down on the header tab and look for 'authorization' (under "Request Headers")
8. Copy the entire value for `authorization:` after the colon and paste it into 'main.py' as `AUTH = <YOUR AUTHORIZATION TOKEN>`
9. Set the parameters (under `#PARAMS`) values according to preference (make, model, and zip)
8. In the command line navigate to the project folder and run `python main.py`


Special thanks to Michael (https://github.com/Michael001154) for help developing the project

---

## VIN Report Bot — browser lifecycle fix

If the Telegram bot answers with
`Locator.count / Locator.wait_for: Target page, context or browser has been closed`,
see **[docs/CPANEL_FIX.md](docs/CPANEL_FIX.md)** for the cause and the
step-by-step cPanel deployment fix.

* `vinpro/browser_manager.py` — per-request browser contexts, bounded
  concurrency, health-checked browser, automatic retry on a dead browser.
* `vinpro/telegram_example.py` — reference handler wiring.
* `vinpro/requirements.txt` — bot-only dependencies (Playwright, PTB).

## Scraper configuration

`main.py` no longer stores credentials in the source file. Export them first:

```
export CARFAX_AUTH='<your authorization token>'
export CARFAX_COOKIE='<optional cookie header>'
export CAR_MAKE=Honda CAR_MODEL=Civic ZIP=10001
python main.py
```
* `deploy/autofix.sh` — **start here.** Finds the bot, installs everything,
  gets Chromium working, and reports the lines still needing an edit.
* `deploy/analyze_bot.py` — parses the bot's source and lists every browser
  lifecycle bug with line numbers.
* `deploy/probe_chromium.sh` — diagnoses a Chromium that will not start.
* `deploy/install_cpanel.sh` — one-shot cPanel installer (fetch, deps,
  Chromium, smoke test, env file).
* `deploy/keepalive.sh` — cron helper that restarts the bot if it died.
* `tests/test_browser_manager.py` — kills the browser mid-render and checks
  the request still completes.
