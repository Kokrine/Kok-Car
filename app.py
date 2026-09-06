"""
Kok-Car Vehicle History Request app.

A small Flask app that provides a "Request Vehicle History Report" page with
full panels: VIN lookup, requester details, report options, live results,
and request history.

VIN decoding (year/make/model/engine/etc.) is real, powered by the free
NHTSA vPIC API (no key required: https://vpic.nhtsa.dot.gov/api/).

Carfax itself does not offer a public API for accident/service/ownership
history. This app supports two sources for that data:

1. Your own Carfax bot, if it exposes a local HTTP endpoint (see
   CARFAX_BOT_URL below) that returns a real Carfax PDF report for a VIN
   using your own already-authorized account. See carfax_web_api.py
   (shipped alongside your bot, not in this repo) for the endpoint this
   app expects.
2. A deterministic DEMO fallback (structured accident/service/ownership
   cards, not a real PDF), seeded from the VIN, used only when the bot
   endpoint is not configured or is unreachable.

To connect your bot, set these environment variables before running the app:

    CARFAX_BOT_URL     e.g. http://127.0.0.1:8000/carfax-lookup
    CARFAX_BOT_SECRET  a shared secret sent as the X-Bot-Secret header
                        (must match the bot's own WEB_API_SECRET)
    CARFAX_BOT_TIMEOUT seconds to wait for a real report before giving up
                        (default 200 -- real reports can take a couple of
                        minutes since they're generated live)

Your bot's endpoint should accept POST {"vin": "..."} and respond with
either:
  - a real PDF (Content-Type: application/pdf) on success, or
  - JSON {"error": "..."} with a non-200 status on failure.

A bot-returned error is shown to the requester as a real failure -- it is
never silently replaced with demo data, since that would misrepresent a
fake report as a real one. Demo data is only used when the bot isn't
configured or the connection itself fails (bot process not running).
"""
import hashlib
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, abort, g, jsonify, render_template, request, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "carfax_requests.db")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

NHTSA_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

CARFAX_BOT_URL = os.environ.get("CARFAX_BOT_URL", "").strip()
CARFAX_BOT_SECRET = os.environ.get("CARFAX_BOT_SECRET", "").strip()
CARFAX_BOT_TIMEOUT = float(os.environ.get("CARFAX_BOT_TIMEOUT", "200"))

PDF_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.pdf$")

REPORT_OPTIONS = [
    {"key": "accidents", "label": "Accident History"},
    {"key": "service", "label": "Service & Maintenance Records"},
    {"key": "ownership", "label": "Ownership History"},
    {"key": "title", "label": "Title & Lien Check"},
    {"key": "odometer", "label": "Odometer Verification"},
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin TEXT NOT NULL,
            year TEXT,
            make TEXT,
            model TEXT,
            trim TEXT,
            requester_name TEXT NOT NULL,
            requester_email TEXT NOT NULL,
            options TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            accident_count INTEGER,
            owner_count INTEGER,
            title_status TEXT,
            data_source TEXT NOT NULL DEFAULT 'demo',
            pdf_filename TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    db.commit()
    db.close()


def decode_vin(vin):
    """Real VIN decode via NHTSA's free vPIC API."""
    response = requests.get(NHTSA_DECODE_URL.format(vin=vin), timeout=10)
    response.raise_for_status()
    results = response.json().get("Results", [])
    data = results[0] if results else {}

    def field(name):
        value = data.get(name, "")
        return value.strip() if isinstance(value, str) else value

    return {
        "vin": vin,
        "year": field("ModelYear"),
        "make": field("Make"),
        "model": field("Model"),
        "trim": field("Trim") or field("Series"),
        "body_class": field("BodyClass"),
        "engine": field("EngineConfiguration") or field("EngineCylinders"),
        "fuel_type": field("FuelTypePrimary"),
        "plant_country": field("PlantCountry"),
        "error_text": field("ErrorText"),
    }


def fetch_bot_pdf(vin):
    """
    Ask the user's own Carfax bot for a real PDF report over a local HTTP
    call. Returns one of:
      ("pdf", bytes)  -- real report fetched successfully
      ("error", str)  -- bot reached but the scrape itself failed (bad VIN,
                          expired cargopolo.com session, etc.) -- callers
                          must surface this, never silently fall back to
                          demo data for it
      (None, None)    -- bot not configured or unreachable (process not
                          running) -- callers should fall back to demo data
    """
    if not CARFAX_BOT_URL:
        return None, None

    headers = {}
    if CARFAX_BOT_SECRET:
        headers["X-Bot-Secret"] = CARFAX_BOT_SECRET

    try:
        response = requests.post(
            CARFAX_BOT_URL,
            json={"vin": vin},
            headers=headers,
            timeout=CARFAX_BOT_TIMEOUT,
        )
    except requests.RequestException:
        return None, None

    content_type = response.headers.get("Content-Type", "")
    if response.status_code == 200 and content_type.startswith("application/pdf"):
        return "pdf", response.content

    try:
        message = response.json().get("error") or f"Bot returned status {response.status_code}"
    except ValueError:
        message = f"Bot returned status {response.status_code}"
    return "error", message


def generate_history_report(vin, options):
    """
    Deterministic DEMO data for the sections Carfax does not expose via a
    public API. Seeded from the VIN so a given VIN always previews the same
    way. NOT real vehicle history -- replace with a licensed data provider
    for production use.
    """
    seed = int(hashlib.sha256(vin.encode("utf-8")).hexdigest(), 16)

    report = {"is_demo_data": True}

    if "accidents" in options:
        accident_count = seed % 3
        events = []
        for i in range(accident_count):
            events.append(
                {
                    "date": f"{2018 + (seed >> (i * 4)) % 6}-{1 + (seed >> (i * 3)) % 12:02d}",
                    "severity": ["Minor", "Moderate", "Severe"][(seed >> (i * 5)) % 3],
                    "description": ["Front-end collision reported", "Rear-end collision reported",
                                     "Side-impact damage reported"][(seed >> (i * 2)) % 3],
                }
            )
        report["accidents"] = {"count": accident_count, "events": events}

    if "service" in options:
        service_count = 3 + (seed % 5)
        records = []
        for i in range(service_count):
            records.append(
                {
                    "date": f"{2019 + (seed >> (i * 3)) % 5}-{1 + (seed >> (i * 6)) % 12:02d}",
                    "mileage": 8000 * (i + 1) + (seed % 4000),
                    "service": ["Oil change", "Tire rotation", "Brake inspection",
                                "Battery replacement", "Multi-point inspection"][(seed >> (i * 4)) % 5],
                }
            )
        report["service"] = {"count": service_count, "records": records}

    if "ownership" in options:
        owner_count = 1 + (seed % 3)
        owners = []
        for i in range(owner_count):
            owners.append(
                {
                    "owner_number": i + 1,
                    "type": "Personal" if (seed >> i) % 2 == 0 else "Fleet/Rental",
                    "estimated_length_years": 1 + (seed >> (i * 2)) % 5,
                }
            )
        report["ownership"] = {"count": owner_count, "owners": owners}

    if "title" in options:
        clean = (seed % 5) != 0
        report["title"] = {
            "status": "Clean" if clean else "Salvage/Branded",
            "lien_on_record": bool((seed >> 3) % 4 == 0),
        }

    if "odometer" in options:
        report["odometer"] = {
            "rollback_detected": bool((seed >> 7) % 11 == 0),
            "last_reported_mileage": 12000 + (seed % 88000),
        }

    return report


@app.route("/")
def carfax_request_page():
    return render_template(
        "carfax_request.html",
        report_options=REPORT_OPTIONS,
        bot_configured=bool(CARFAX_BOT_URL),
    )


@app.route("/reports/<filename>")
def download_report(filename):
    if not PDF_FILENAME_RE.match(filename):
        abort(404)
    return send_from_directory(REPORTS_DIR, filename, mimetype="application/pdf")


@app.route("/api/decode-vin/<vin>")
def api_decode_vin(vin):
    vin = vin.strip().upper()
    if len(vin) != 17:
        return jsonify({"error": "VIN must be exactly 17 characters."}), 400
    try:
        return jsonify(decode_vin(vin))
    except requests.RequestException as exc:
        return jsonify({"error": f"VIN decode service unavailable: {exc}"}), 502


@app.route("/api/request-report", methods=["POST"])
def api_request_report():
    payload = request.get_json(force=True, silent=True) or {}
    vin = (payload.get("vin") or "").strip().upper()
    requester_name = (payload.get("requester_name") or "").strip()
    requester_email = (payload.get("requester_email") or "").strip()
    options = [opt for opt in (payload.get("options") or []) if opt in {o["key"] for o in REPORT_OPTIONS}]

    errors = {}
    if len(vin) != 17:
        errors["vin"] = "VIN must be exactly 17 characters."
    if not requester_name:
        errors["requester_name"] = "Requester name is required."
    if not requester_email or "@" not in requester_email:
        errors["requester_email"] = "A valid email is required."
    if not options:
        errors["options"] = "Select at least one report section."
    if errors:
        return jsonify({"errors": errors}), 400

    try:
        vehicle = decode_vin(vin)
    except requests.RequestException as exc:
        return jsonify({"error": f"VIN decode service unavailable: {exc}"}), 502

    bot_status, bot_payload = fetch_bot_pdf(vin)

    if bot_status == "error":
        return jsonify({"error": f"Live Carfax report failed: {bot_payload}"}), 502

    pdf_filename = None
    if bot_status == "pdf":
        pdf_filename = f"{uuid.uuid4().hex}.pdf"
        with open(os.path.join(REPORTS_DIR, pdf_filename), "wb") as f:
            f.write(bot_payload)
        history = {"is_demo_data": False, "pdf_available": True}
    else:
        history = generate_history_report(vin, options)

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO requests
            (vin, year, make, model, trim, requester_name, requester_email,
             options, status, accident_count, owner_count, title_status,
             data_source, pdf_filename, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)
        """,
        (
            vin,
            vehicle.get("year"),
            vehicle.get("make"),
            vehicle.get("model"),
            vehicle.get("trim"),
            requester_name,
            requester_email,
            ",".join(options),
            history.get("accidents", {}).get("count"),
            history.get("ownership", {}).get("count"),
            history.get("title", {}).get("status"),
            "demo" if history.get("is_demo_data") else "bot",
            pdf_filename,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()

    result = {
        "request_id": cursor.lastrowid,
        "vehicle": vehicle,
        "history": history,
    }
    if pdf_filename:
        result["pdf_url"] = f"/reports/{pdf_filename}"
    return jsonify(result)


@app.route("/api/history")
def api_history():
    db = get_db()
    rows = db.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify([dict(row) for row in rows])


init_db()

if __name__ == "__main__":
    # threaded=True matters here: a live bot-backed request can take up to
    # CARFAX_BOT_TIMEOUT seconds, and the dev server is single-threaded by
    # default -- without this, one in-flight request would block every
    # other page load (including /api/history).
    app.run(debug=True, threaded=True)
