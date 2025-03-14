#!/usr/bin/env python3
import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime, timedelta
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
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"

# The documented endpoint (from API(1).md).
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: we’ll keep your same times for display purposes,
# but we will clamp the "to" date if it’s in the future so that
# we do not violate "Cannot query future dates."
RACE_START_DATE = "2025-03-13"
RACE_END_DATE   = "2025-03-21"

# We also store the exact times for the countdown, etc.
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# Cache for top wagers
data_cache = {}

# ------------------------------------------------------------------------------------
# LOGGING UTILITY
# ------------------------------------------------------------------------------------
def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# ------------------------------------------------------------------------------------
# FETCHING FROM UPGRADER
# ------------------------------------------------------------------------------------
def fetch_data_from_upgrader():
    """
    Attempts to call the /affiliate/creator/get-stats API with a JSON POST body.
    Must not include any future date for 'to' or it can fail.
    """
    global data_cache

    now_utc = datetime.utcnow()

    # If it’s before the race starts, we can just say "Not started."
    if now_utc < RACE_START_TIME:
        log_message("info", "Wager race not started yet.")
        data_cache = {"error": "Race not started yet."}
        return

    # If race is over, we can simply say "Ended."
    if now_utc > RACE_END_TIME:
        log_message("info", "Wager race ended.")
        data_cache = {"error": "Race ended."}
        return

    # According to the doc: "Cannot query future dates."
    # So if RACE_END_DATE is beyond 'today', clamp it to today’s date in YYYY-MM-DD
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if RACE_END_DATE > today_str:
        # Force the 'to' field to be "today" so we don't break the rule
        valid_to_date = today_str
    else:
        valid_to_date = RACE_END_DATE

    payload = {
        "apikey": UPGRADER_API_KEY,
        "from": RACE_START_DATE,
        "to":   valid_to_date
    }

    # Make sure to send JSON with correct headers.
    headers = {
        "Content-Type": "application/json"
    }

    # Attempt the POST request
    try:
        log_message("info", f"[Attempting POST] {UPGRADER_API_ENDPOINT} with {payload}")
        resp = requests.post(
            UPGRADER_API_ENDPOINT,
            json=payload,             # ensures it’s sent as JSON
            headers=headers,
            timeout=15
        )

        if resp.status_code == 200:
            resp_json = resp.json()
            # Check if the API itself indicates an error:
            if resp_json.get("error", True) is True:
                # The API says: error = true
                msg = resp_json.get("msg", "Unknown API error")
                log_message("error", f"Upgrader responded with an error: {msg}")
                data_cache = {"error": msg}
            else:
                # Parse the data
                data = resp_json.get("data", {})
                summarized = data.get("summarizedBets", [])

                # Sort them in descending order by "wager"
                sorted_bets = sorted(
                    summarized,
                    key=lambda i: i.get("wager", 0),
                    reverse=True
                )

                # Convert the top 11 to your standard dictionary
                top_entries = {}
                for index, item in enumerate(sorted_bets[:11], start=1):
                    username = item.get("user", {}).get("username", f"Player{index}")
                    cents_wager = item.get("wager", 0)
                    dollars_str = f"${cents_wager/100:,.2f}"
                    top_entries[f"top{index}"] = {
                        "username": username,
                        "wager": dollars_str
                    }
                # If fewer than 11 found, fill placeholders
                if len(sorted_bets) < 11:
                    for j in range(len(sorted_bets)+1, 12):
                        top_entries[f"top{j}"] = {
                            "username": f"Player{j}",
                            "wager": "$0.00"
                        }

                data_cache = top_entries
                log_message("info", f"Data cache updated with {len(top_entries)} top entries.")
        else:
            # If not 200, log + store error
            log_message("error", f"HTTP {resp.status_code} => {resp.text[:300]}")
            data_cache = {"error": f"HTTP {resp.status_code} from Upgrader."}

    except Exception as ex:
        log_message("error", f"Exception calling Upgrader: {ex}")
        data_cache = {"error": str(ex)}

def schedule_data_fetch():
    """
    Fetch immediately, then schedule again in 90 seconds.
    """
    fetch_data_from_upgrader()
    threading.Timer(90, schedule_data_fetch).start()

# ------------------------------------------------------------------------------------
# FLASK ROUTES
# ------------------------------------------------------------------------------------
@app.route("/data")
def get_data():
    log_message("info", "Client requested /data endpoint.")
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message("info", "Serving index.html page.")
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(e):
    log_message("warning", "404 - Page not found.")
    return render_template("404.html"), 404

# ------------------------------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    schedule_data_fetch()
    port = int(os.getenv("PORT", 8080))
    log_message("info", f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
