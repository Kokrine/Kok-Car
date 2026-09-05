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
keyless [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/api/). Carfax has no public
API for accident/service/ownership/title history, so those sections come from
one of two sources:

1. **Your own Telegram Carfax bot**, if you point the page at it (see below).
2. A deterministic **demo fallback**, seeded from the VIN, used whenever the
   bot isn't configured or doesn't respond in time. Every report and every row
   in the request-history panel is labeled Demo or Live so it's always clear
   which one you're looking at.

### Run it

```
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000/.

### Connecting your Telegram Carfax bot (optional)

If your bot already fetches real reports using your own dealer account, you
can point this page at it instead of using demo data. The page never talks to
Telegram directly — it makes one local HTTP call to your bot each time someone
submits a request, so there's no polling, no chat IDs, and no waiting on a
Telegram round-trip.

**1. Add a small endpoint to your existing bot script.** It needs to accept a
VIN and the requested report sections, and return them in this shape (only
include the sections that were requested):

```python
# Add this to your bot's own process (Flask shown; any framework works).
from flask import Flask, jsonify, request

bot_api = Flask(__name__)
BOT_SECRET = "choose-a-long-random-string"  # must match CARFAX_BOT_SECRET below

@bot_api.route("/carfax-lookup", methods=["POST"])
def carfax_lookup():
    if request.headers.get("X-Bot-Secret") != BOT_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json()
    vin = payload["vin"]
    options = payload["options"]  # e.g. ["accidents", "title"]

    # Call whatever function your bot already uses to pull a real report
    # for `vin` using your dealer session, then shape the result like this:
    return jsonify({
        "accidents": {"count": 1, "events": [
            {"date": "2022-03", "severity": "Minor", "description": "Front bumper"}
        ]},
        "title": {"status": "Clean", "lien_on_record": False},
        # ...include "service", "ownership", "odometer" the same way if requested
    })

bot_api.run(port=8000)  # run this alongside your Telegram bot process
```

**2. Point the web page at it** by setting environment variables before
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

That's it — submit a request on the page and it will call your bot first;
the results panel and history table will show **Live (bot)** instead of
**Demo**. If the bot is down or the URL isn't set, requests still work using
demo data, so the page is never broken by the bot being offline.

Since this reuses your own already-authorized dealer session rather than a
public API, keep `CARFAX_BOT_SECRET` private and don't expose the bot's port
to the public internet — it should only be reachable from `app.py` on the
same machine (or your own private network).

---

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
