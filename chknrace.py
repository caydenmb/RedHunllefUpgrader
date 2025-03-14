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
# CONFIGURATION / CONSTANTS (matches doc-based request format)
# ------------------------------------------------------------------------------------
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"  # <= Must be valid & under 100 chars
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: from 2025-03-13 (3 AM) to 2025-03-21 (3 AM).
# We use "from", "to" in YYYY-MM-DD format in the POST body, as the doc shows.
RACE_START_DATE = "2025-03-13"  
RACE_END_DATE   = "2025-03-21"  

# We also track exact times for internal checks (not part of doc, but useful).
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# Our data cache for storing the “top wagers.”
data_cache = {}

# ------------------------------------------------------------------------------------
# LOGGING UTILITY
# ------------------------------------------------------------------------------------
def log_message(level, message):
    """
    Basic logger that includes timestamp and log level.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] [{level.upper()}]: {message}")

# ------------------------------------------------------------------------------------
# FETCH DATA FUNCTION
# ------------------------------------------------------------------------------------
def fetch_data_from_api():
    """
    Performs a POST request to /affiliate/creator/get-stats, with JSON body:
      {
        "apikey": "xxxx",
        "from": "YYYY-MM-DD",
        "to":   "YYYY-MM-DD"
      }
    per the official doc. If the current time is outside our race window,
    we store an error in data_cache. Otherwise, parse the API response.
    
    NOTE:
    - The doc says the endpoint has a 5-minute cooldown & rate limit. We fetch more 
      frequently here (every 90s), which may lead to "Rate limit exceeded" errors.
    """
    global data_cache

    now_utc = datetime.utcnow()

    # Check race window
    if now_utc < RACE_START_TIME:
        log_message('info', "Race not started yet.")
        data_cache = {"error": "Race has not started yet."}
        return
    if now_utc > RACE_END_TIME:
        log_message('info', "Race ended.")
        data_cache = {"error": "Race has ended."}
        return

    # Prepare request payload, exactly as doc's example
    payload = {
        "apikey": UPGRADER_API_KEY,  # string, required
        "from": RACE_START_DATE,     # date in YYYY-MM-DD
        "to":   RACE_END_DATE        # date in YYYY-MM-DD
    }

    # We can optionally do up to 3 attempts if there's a transient 5xx error
    max_retries = 3
    attempt = 0

    while attempt < max_retries:
        attempt += 1
        try:
            log_message('info', f"[Attempt {attempt}/{max_retries}] POST to {UPGRADER_API_ENDPOINT} with: {payload}")
            response = requests.post(UPGRADER_API_ENDPOINT, json=payload, timeout=15)

            if response.status_code == 200:
                resp_json = response.json()
                log_message('debug', f"Raw API response: {json.dumps(resp_json)}")

                # Per doc, if "error" is true => there's an error. Otherwise "data" is your result object.
                if resp_json.get("error", True):
                    msg = resp_json.get("msg", "Unknown error from Upgrader")
                    log_message('error', f"Upgrader API indicates error: {msg}")
                    data_cache = {"error": msg}
                    return
                else:
                    # The doc says the data is in "data" => includes "summarizedBets", "affiliate", etc.
                    data_section = resp_json.get("data", {})
                    summarized_bets = data_section.get("summarizedBets", [])

                    # Sort by "wager" descending (these wagers are in cents, per doc).
                    sorted_bets = sorted(
                        summarized_bets,
                        key=lambda b: b.get("wager", 0),
                        reverse=True
                    )

                    # Build a top-11 structure for the front end
                    top_entries = {}
                    for i, entry in enumerate(sorted_bets[:11], start=1):
                        # Convert "wager" from cents to a nicer string
                        cents_val = entry.get("wager", 0)
                        dollars_str = f"${(cents_val / 100):,.2f}"

                        # user.username per doc
                        username = entry.get("user", {}).get("username", f"Player{i}")

                        top_entries[f"top{i}"] = {
                            "username": username,
                            "wager": dollars_str
                        }

                    # If fewer than 11, fill placeholders
                    for j in range(len(sorted_bets[:11]) + 1, 12):
                        top_entries[f"top{j}"] = {
                            "username": f"Player{j}",
                            "wager": "$0.00"
                        }

                    data_cache = top_entries
                    log_message('info', f"Data cache updated with {len(top_entries)} entries.")
                    return  # Success
            else:
                log_message('error', f"HTTP {response.status_code} => {response.text}")
                if 400 <= response.status_code < 500:
                    # Likely "Invalid date format", "Invalid API key", etc. => doc mentions these
                    data_cache = {"error": f"Client error {response.status_code}."}
                    return
                else:
                    # 5xx => attempt retry
                    if attempt < max_retries:
                        log_message('warning', "Server error. Retrying in 5s...")
                        time.sleep(5)
                    else:
                        data_cache = {"error": f"HTTP {response.status_code} after {max_retries} attempts."}
                        return

        except requests.exceptions.RequestException as ex:
            log_message('error', f"Network/Request exception on attempt {attempt}: {ex}")
            if attempt < max_retries:
                log_message('warning', "Retrying in 5s...")
                time.sleep(5)
            else:
                data_cache = {"error": f"Network error after {max_retries} attempts."}
                return

# ------------------------------------------------------------------------------------
# SCHEDULER
# ------------------------------------------------------------------------------------
def schedule_data_fetch():
    """
    Immediately fetch data upon server start, then schedule next fetch in 90 seconds.
    NOTE: The doc says there's a 5-min cooldown (300s). We're ignoring that here,
    so you might see "Rate limit exceeded" if the real API enforces it strictly.
    """
    fetch_data_from_api()
    threading.Timer(90, schedule_data_fetch).start()

# ------------------------------------------------------------------------------------
# FLASK ROUTES
# ------------------------------------------------------------------------------------
@app.route("/data")
def get_data():
    log_message('info', "Client requested /data endpoint.")
    # We simply return our cached top wagers structure (or error) as JSON
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message('info', "Serving index.html page.")
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(e):
    log_message('warning', "404 - page not found.")
    return render_template("404.html"), 404

# ------------------------------------------------------------------------------------
# MAIN SCRIPT
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    schedule_data_fetch()
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
