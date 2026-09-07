# Disclaimer

* I do not promote, encourage, support or excite any illegal activity or hacking without written permission in general. The repo and author of the repo is no way responsible for any misuse of the information.

* "carfax-scraper" is just a terms that represents the name of the repo and is not a repo that provides any illegal information.

* The Software's and Scripts provided by the repo should only be used for **_EDUCATIONAL PURPOSES ONLY_**. The repo or the author can not be held responsible for the misuse of them by the users.

* I am not responsible for any direct or indirect damage caused due to the usage of the code provided on this site. All the information provided on this repo are for educational purposes only.



## Vehicle History Request Page

A Flask web app (`app.py`) provides a "Request Vehicle History Report" page at `/`
with full panels: VIN lookup, requester details, report section options, a
submit/status panel, a results panel, and a request-history panel backed by a
local SQLite database.

VIN decoding (year/make/model/trim/engine/etc.) is real, powered by the free,
keyless [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/api/). The full vehicle
history report comes from one of two sources:

1. **Your own Carfax bot**, if you point the page at it (see below) — this
   returns a real Carfax PDF, generated live through your own account.
2. A deterministic **demo fallback** (structured accident/service/ownership
   cards, not a real PDF), seeded from the VIN, used only when the bot isn't
   configured or its process isn't reachable. Every report and every row in
   the request-history panel is labeled Demo or Live so it's always clear
   which one you're looking at. If the bot *is* reachable but the report
   itself fails (bad VIN, expired session, etc.), that failure is shown as a
   real error — it is never replaced with demo data, since that would
   misrepresent a fake report as a real one.

### Run it

```
pip install -r requirements.txt
python app.py
```

Configuration (`CARFAX_BOT_URL`, `CARFAX_BOT_SECRET`, etc.) can be set as
real environment variables, or placed in a `.env` file next to `app.py` —
it's loaded automatically. Useful extra settings for a real deployment:

    FLASK_HOST   interface to bind (default 127.0.0.1 -- put a reverse
                 proxy in front rather than binding 0.0.0.0 directly)
    FLASK_PORT   port to bind (default 5000)
    FLASK_DEBUG  set to "true" only for local development -- never on a
                 server reachable by anyone but you (the Werkzeug debugger
                 allows arbitrary code execution if reachable)

Then open http://127.0.0.1:5000/.

### Connecting your Carfax bot (optional)

If you already have a bot that fetches real Carfax PDFs using your own
account, point this page at it instead of using demo data. The page never
talks to Telegram — it makes one local HTTP call each time someone submits a
request, so there's no polling and no chat IDs involved.

**1. Add a small companion HTTP server next to your bot** that exposes its
existing report-fetching function over `POST /carfax-lookup`, expecting
`{"vin": "..."}` and returning either a real PDF (`Content-Type:
application/pdf`) or a JSON `{"error": "..."}` with a non-200 status. Run it
as its own process alongside your bot — don't modify your bot's own script.
Reuse your bot's already-authorized session/function rather than
reimplementing it.

**2. Point this page at it** by setting environment variables before
starting `app.py`:

```
# Windows (cmd.exe)
set CARFAX_BOT_URL=http://127.0.0.1:8000/carfax-lookup
set CARFAX_BOT_SECRET=choose-a-long-random-string
python app.py

# Git Bash / macOS / Linux
export CARFAX_BOT_URL=http://127.0.0.1:8000/carfax-lookup
export CARFAX_BOT_SECRET=choose-a-long-random-string
python app.py
```

`CARFAX_BOT_TIMEOUT` (seconds, default 200) controls how long the page waits
for a real report before giving up — real reports are generated live and can
take a couple of minutes.

That's it — submit a request and the page calls your bot first; the results
panel shows a **Download PDF** button and the history table marks the row
**Live (bot)**. If the bot isn't configured or its process is down, requests
still work using demo data, so the page is never broken by the bot being
offline.

Since this reuses your own already-authorized account/session, keep
`CARFAX_BOT_SECRET` private and never expose the bot's port to the public
internet — it should only be reachable from `app.py` on the same machine (or
your own private network).

---

## Usage Instructions 

(Google Chrome only; only tested on Mac OS) 



1. Copy repo:
   
`git clone https://github.com/grsahagian/carfax-scraper`


2. Install dependencies: `pip install -r requirements-scraper.txt` (this
   script's own dependencies -- pandas, requests -- are separate from the
   web app's `requirements.txt` above, so installing one never requires
   the other)
   
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
