#!/usr/bin/env python3

import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime, timedelta
import os
import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Hard-coded API key for Upgrader
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"

# According to the doc, the path is /affiliate/creator/get-stats, Method: POST
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: From March 13 at 3 AM to March 21 at 3 AM
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# We store the "top wagers" or error messages here
data_cache = {}

def log_message(level, message):
    """
    Simple log helper to unify timestamp + log level format.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper()}]: {message}")

def fetch_data_from_upgrader():
    """
    Attempt to POST to the Upgrader endpoint with the doc's JSON body.
    We see a 405 or 5xx in practice, meaning the server might be disallowing POST
    or configured differently than the docs claim. This function logs whatever
    HTTP status is returned and updates data_cache accordingly.
    """
    now_utc = datetime.utcnow()

    # If the race hasn't started, store a note and skip
    if now_utc < RACE_START_TIME:
        data_cache["error"] = "Race has not started yet."
        return

    # If the race is over, store a note and skip
    if now_utc > RACE_END_TIME:
        data_cache["error"] = "Race has ended."
        return

    # Build the body for the POST, as per doc
    payload = {
        "apikey": UPGRADER_API_KEY,
        "from": "2025-03-13",
        "to":   "2025-03-21"
    }

    log_message("info", f"[Attempting POST] {UPGRADER_API_ENDPOINT} with {payload}")

    try:
        resp = requests.post(UPGRADER_API_ENDPOINT, json=payload, timeout=15)
        if resp.status_code == 200:
            log_message("info", f"HTTP 200 OK; server text: {resp.text[:300]}")
            # Here you’d parse JSON if it truly returned data
            # e.g. data_obj = resp.json()
            # Then store top wagers in data_cache. But with 405 or 5xx, we never get this far.
        else:
            log_message("error", f"HTTP {resp.status_code} => {resp.text[:300]}")
            data_cache["error"] = (
                f"Upgrader server responded with {resp.status_code}. "
                "Likely the server is not accepting POST at this route or a mismatch in docs."
            )
    except Exception as e:
        log_message("error", f"Exception: {str(e)}")
        data_cache["error"] = f"Request exception: {str(e)}"

def schedule_fetch():
    """
    Call fetch_data_from_upgrader() immediately, then schedule repeats every 90 seconds.
    """
    fetch_data_from_upgrader()
    threading.Timer(90, schedule_fetch).start()

@app.route("/data")
def get_data():
    """
    Return whatever we have in data_cache (either top wagers or an error).
    """
    log_message("info", "Client requested /data endpoint.")
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    """
    Serve the main index.html template.
    """
    log_message("info", "Serving index.html page.")
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(_err):
    """
    Custom 404, serve 404.html template.
    """
    log_message("warning", "404 - Page not found.")
    return render_template("404.html"), 404

if __name__ == "__main__":
    # Start repeated data fetching
    schedule_fetch()

    # Launch Flask on port from env or default 8080
    port = int(os.getenv("PORT", 8080))
    log_message("info", f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
