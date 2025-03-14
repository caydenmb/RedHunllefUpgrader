#!/usr/bin/env python3
import requests
import time
import json
import random
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
# CONFIGURATION / CONSTANTS (unchanged from your existing logic, except for CF workaround)
# ------------------------------------------------------------------------------------
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"  # <= Provided API key (must be <100 chars)
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: from 2025-03-13 at 3 AM to 2025-03-21 at 3 AM
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

RACE_START_DATE = "2025-03-13"  # For the API "from" field (YYYY-MM-DD)
RACE_END_DATE   = "2025-03-21"  # For the API "to" field (YYYY-MM-DD)

# Data cache for scoreboard results
data_cache = {}

# ------------------------------------------------------------------------------------
# CLOUDFLARE WORKAROUND:
# We'll create a "session" object that uses typical browser-like headers,
# random delays, and some backoff logic if we see 5xx/520 from Cloudflare.
# ------------------------------------------------------------------------------------
session = requests.Session()

# Update session headers to look like a real browser
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
})

def log_message(level, message):
    """
    Simple logger with timestamps. This matches your style of logging.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] [{level.upper()}]: {message}")

# ------------------------------------------------------------------------------------
# FETCH DATA FUNCTION
# ------------------------------------------------------------------------------------
def fetch_data_from_api():
    """
    Sends a POST request to the official Upgrader.com endpoint,
    passing "apikey", "from", "to" in JSON, as per doc.

    We wrap it in multiple tries, adding random sleeps + backoff
    to reduce the chance Cloudflare returns 520.
    """
    global data_cache

    now_utc = datetime.utcnow()

    # Check if race started/ended:
    if now_utc < RACE_START_TIME:
        log_message("info", "Race has NOT started yet.")
        data_cache = {"error": "Race has not started yet."}
        return

    if now_utc > RACE_END_TIME:
        log_message("info", "Race has ENDED.")
        data_cache = {"error": "Race has ended."}
        return

    # Prepare request body exactly as doc's structure:
    payload = {
        "apikey": UPGRADER_API_KEY,
        "from": RACE_START_DATE,
        "to":   RACE_END_DATE
    }

    max_retries = 3
    attempt = 0

    while attempt < max_retries:
        attempt += 1
        # Add a small random delay to mimic human-like behavior
        time.sleep(random.uniform(0.2, 1.0))

        try:
            log_message("info", f"[Attempt {attempt}/{max_retries}] Requesting {UPGRADER_API_ENDPOINT} with payload: {payload}")
            response = session.post(
                UPGRADER_API_ENDPOINT,
                json=payload,
                timeout=15
            )

            if response.status_code == 200:
                # Good. Parse the JSON from the doc:
                resp_json = response.json()
                log_message("debug", f"Raw Upgrader API response: {json.dumps(resp_json)}")

                # The doc indicates if "error" = true => there's a problem
                if resp_json.get("error", True):
                    # We have an error from the Upgrader side
                    msg = resp_json.get("msg", "Unknown error from Upgrader API")
                    log_message("error", f"Upgrader API indicates error: {msg}")
                    data_cache = {"error": msg}
                    return
                else:
                    # No error => parse the "data" block
                    data_section = resp_json.get("data", {})
                    summarized_bets = data_section.get("summarizedBets", [])

                    # Sort by "wager" descending
                    sorted_bets = sorted(
                        summarized_bets,
                        key=lambda b: b.get("wager", 0),
                        reverse=True
                    )

                    # Build a scoreboard for top 11
                    top_entries = {}
                    for i, entry in enumerate(sorted_bets[:11], start=1):
                        cents_val = entry.get("wager", 0)
                        dollars_str = f"${(cents_val / 100):,.2f}"

                        username = entry.get("user", {}).get("username", f"Player{i}")
                        top_entries[f"top{i}"] = {
                            "username": username,
                            "wager": dollars_str
                        }

                    # If fewer than 11, fill placeholders
                    existing_count = len(sorted_bets[:11])
                    for fill_i in range(existing_count + 1, 12):
                        top_entries[f"top{fill_i}"] = {
                            "username": f"Player{fill_i}",
                            "wager": "$0.00"
                        }

                    data_cache = top_entries
                    log_message("info", f"Data cache updated with {len(top_entries)} top entries.")
                return  # Done, success
            else:
                # Non-200 => likely 520 from Cloudflare or other error
                log_message("error", f"HTTP {response.status_code} => {response.text[:300]}")
                # If 4xx => probably a client error from doc (invalid key, etc.)
                if 400 <= response.status_code < 500:
                    data_cache = {"error": f"Client error {response.status_code} from Upgrader."}
                    return
                else:
                    # 5xx => Cloudflare or server error => wait + retry
                    if attempt < max_retries:
                        backoff_secs = 5 + attempt * 2
                        log_message("warning", f"Server error {response.status_code}, waiting {backoff_secs}s before retry.")
                        time.sleep(backoff_secs)
                    else:
                        data_cache = {"error": f"HTTP {response.status_code} after {max_retries} attempts."}
                        return

        except requests.exceptions.RequestException as ex:
            # For any network or request exception
            log_message("error", f"RequestException on attempt {attempt}: {ex}")
            if attempt < max_retries:
                backoff_secs = 5 + attempt * 2
                log_message("warning", f"Retrying in {backoff_secs}s after network error.")
                time.sleep(backoff_secs)
            else:
                data_cache = {"error": f"Network error after {max_retries} attempts."}
                return

# ------------------------------------------------------------------------------------
# SCHEDULER (unchanged except for the code inside fetch_data_from_api)
# ------------------------------------------------------------------------------------
def schedule_data_fetch():
    """
    Calls fetch_data_from_api() upon start, then schedules again in 90s.
    (Yes, the doc says 5-min cooldown, but we're keeping your existing timing.)
    """
    fetch_data_from_api()
    threading.Timer(90, schedule_data_fetch).start()

# ------------------------------------------------------------------------------------
# FLASK ROUTES (unchanged)
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
    log_message("warning", "404 - page not found.")
    return render_template("404.html"), 404

# ------------------------------------------------------------------------------------
# MAIN SCRIPT
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    schedule_data_fetch()
    port = int(os.getenv("PORT", 8080))
    log_message("info", f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
