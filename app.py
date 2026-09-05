"""
Kok-Car Vehicle History Request app.

A small Flask app that provides a "Request Vehicle History Report" page with
full panels: VIN lookup, requester details, report options, live results,
and request history.

VIN decoding (year/make/model/engine/etc.) is real, powered by the free
NHTSA vPIC API (no key required: https://vpic.nhtsa.dot.gov/api/).

Carfax itself does not offer a public API for accident/service/ownership
history, so those sections are generated as clearly-labeled DEMO data,
deterministically derived from the VIN so the same VIN always previews the
same way. Swap `generate_history_report()` for a real vendor integration
(Carfax for Dealers, AutoCheck, NMVTIS, etc.) once you have credentials.
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

import requests
from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carfax_requests.db")
NHTSA_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

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
    return render_template("carfax_request.html", report_options=REPORT_OPTIONS)


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

    history = generate_history_report(vin, options)

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO requests
            (vin, year, make, model, trim, requester_name, requester_email,
             options, status, accident_count, owner_count, title_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?)
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
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()

    return jsonify(
        {
            "request_id": cursor.lastrowid,
            "vehicle": vehicle,
            "history": history,
        }
    )


@app.route("/api/history")
def api_history():
    db = get_db()
    rows = db.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify([dict(row) for row in rows])


init_db()

if __name__ == "__main__":
    app.run(debug=True)
