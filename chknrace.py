#!/usr/bin/env python3
import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

# ------------------------------------------------------------------------------------
# Flask app initialization
# ------------------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# ------------------------------------------------------------------------------------
# CONFIGURATION / CONSTANTS
# ------------------------------------------------------------------------------------
# Upgrader Creator API key
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"

# Endpoint from your "API(1).md" file
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: (March 13 at 3 AM) to (March 21 at 3 AM)
# Using date-level granularity for the POST body ("from", "to"),
# but also storing exact times for internal checks to show if race not started/ended.
RACE_START_DATE = "2025-03-13"  # "from" in YYYY-MM-DD
RACE_END_DATE   = "2025-03-21"  # "to" in YYYY-MM-DD

# Fixed times for 3:00 AM UTC on start/end dates
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# Data cache for storing parsed “top wagerers”.
data_cache = {}

# ------------------------------------------------------------------------------------
# UTILITY FUNCTIONS
# ------------------------------------------------------------------------------------
def log_message(level, message):
    """
    Log helper for timestamped, leveled logs in the console.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

def fetch_data_from_api():
    """
    Fetch data from Upgrader's /affiliate/creator/get-stats API using a JSON POST with:
        {
            "apikey": "YOUR_API_KEY",
            "from": "YYYY-MM-DD",
            "to":   "YYYY-MM-DD"
        }
    We'll only do this if the current UTC time is within our race window.
    Otherwise, store a simple "error" in data_cache for the front-end.

    NEW: We added a short retry loop (up to 3 attempts) for any 5xx response
    or RequestException, to handle intermittent Cloudflare errors.
    """
    global data_cache

    now_utc = datetime.utcnow()

    # If race hasn’t started:
    if now_utc < RACE_START_TIME:
        log_message('info', 'Race has NOT started yet.')
        data_cache = {"error": "Race has not started yet."}
        return

    # If race is over:
    if now_utc > RACE_END_TIME:
        log_message('info', 'Race has ENDED.')
        data_cache = {"error": "Race has ended."}
        return

    # Otherwise, prepare the POST payload (matching the API doc)
    payload = {
        "apikey": UPGRADER_API_KEY,
        "from": RACE_START_DATE,
        "to":   RACE_END_DATE
    }

    # We'll do up to 3 attempts if 5xx or network error occurs
    max_retries = 3
    attempt = 0

    while attempt < max_retries:
        attempt += 1
        try:
            log_message('info', f"[Attempt {attempt}/{max_retries}] Requesting {UPGRADER_API_ENDPOINT} with payload: {payload}")
            response = requests.post(UPGRADER_API_ENDPOINT, json=payload, timeout=15)

            # If server didn't return 200 OK, see if we should retry or not
            if response.status_code == 200:
                # Parse JSON
                resp_json = response.json()
                log_message('debug', f"Raw Upgrader API response: {json.dumps(resp_json)}")

                # If "error" is True in the response, the API indicates a problem
                if resp_json.get("error", True):
                    msg = resp_json.get("msg", "Unknown error from Upgrader")
                    log_message('error', f"Upgrader API indicates error: {msg}")
                    data_cache = {"error": msg}
                    return
                # Otherwise parse the "summarizedBets"
                data_section = resp_json.get("data", {})
                summarized_bets = data_section.get("summarizedBets", [])

                # Sort by "wager" descending; "wager" is in cents
                sorted_bets = sorted(
                    summarized_bets,
                    key=lambda item: item.get("wager", 0),
                    reverse=True
                )

                # Build a dictionary for top 11 (1..11)
                top_entries = {}
                for i, entry in enumerate(sorted_bets[:11], start=1):
                    cents = entry.get("wager", 0)
                    dollars_str = f"${(cents / 100):,.2f}"
                    username = entry.get("user", {}).get("username", f"Player{i}")
                    top_entries[f"top{i}"] = {
                        "username": username,
                        "wager": dollars_str
                    }

                # Fill placeholders for missing ranks if fewer than 11
                total_in_sorted = len(sorted_bets[:11])
                if total_in_sorted < 11:
                    for j in range(total_in_sorted + 1, 12):
                        top_entries[f"top{j}"] = {
                            "username": f"Player{j}",
                            "wager": "$0.00"
                        }

                # Update the data cache and done
                data_cache = top_entries
                log_message('info', f"Data cache updated with {len(top_entries)} top entries.")
                return

            else:
                # Non-200 response => possibly 5xx or 4xx
                log_message('error', f"HTTP {response.status_code} => {response.text}")

                if 400 <= response.status_code < 500:
                    # If it's 4xx, it's a client error => do not retry further
                    data_cache = {"error": f"Client error {response.status_code}. Check API key or request."}
                    return
                else:
                    # 5xx error => attempt retry if not at max
                    if attempt < max_retries:
                        log_message('warning', f"Will retry after short delay (5s).")
                        time.sleep(5)
                    else:
                        data_cache = {"error": f"HTTP {response.status_code} after {max_retries} attempts."}
                        return

        except requests.exceptions.RequestException as ex:
            # Network / request error => can retry up to max_retries
            log_message('error', f"Network error on attempt {attempt}: {str(ex)}")
            if attempt < max_retries:
                log_message('warning', "Retrying after 5s delay...")
                time.sleep(5)
            else:
                data_cache = {"error": f"Network error after {max_retries} attempts."}
                return

def schedule_data_fetch():
    """
    Schedule periodic calls to fetch_data_from_api() every 5 minutes.
    """
    fetch_data_from_api()
    threading.Timer(300, schedule_data_fetch).start()  # 300 seconds = 5 minutes

# ------------------------------------------------------------------------------------
# FLASK ROUTES
# ------------------------------------------------------------------------------------
@app.route("/data")
def get_data():
    """
    Returns the cached top wagers as JSON for the front-end (index.html).
    """
    log_message('info', "Client requested /data endpoint.")
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    """
    Renders the main index.html page from templates.
    """
    log_message('info', "Serving index.html page.")
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(e):
    """
    Custom 404 page if a user visits an unknown route.
    """
    log_message('warning', "404 - Page not found.")
    return render_template("404.html"), 404

# ------------------------------------------------------------------------------------
# MAIN SCRIPT EXECUTION
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    # Begin scheduled data fetches
    schedule_data_fetch()

    # Start Flask server
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
