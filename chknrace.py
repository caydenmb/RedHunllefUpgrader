#!/usr/bin/env python3
import cloudscraper
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

# ------------------------------------------------------------------------------------
# Flask App Initialization
# ------------------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# ------------------------------------------------------------------------------------
# Configuration / Constants
# ------------------------------------------------------------------------------------
# Upgrader Creator API key and endpoint (per API(1).md documentation)
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"
# Endpoint per the API documentation (POST method)
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window: (March 13 at 3 AM) to (March 21 at 3 AM)
# The API will be queried only during the race window.
RACE_START_DATE = "2025-03-13"  # For the JSON payload "from"
RACE_END_DATE   = "2025-03-21"  # For the JSON payload "to"

# Fixed times for 3:00 AM UTC on start and end dates
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# Data cache for storing parsed “top wagerers”
data_cache = {}

# ------------------------------------------------------------------------------------
# Logging Utility Function
# ------------------------------------------------------------------------------------
def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# ------------------------------------------------------------------------------------
# Function to fetch data from Upgrader API using cloudscraper
# ------------------------------------------------------------------------------------
def fetch_data_from_api():
    global data_cache
    try:
        now_utc = datetime.utcnow()

        # Check if race hasn't started or has ended
        if now_utc < RACE_START_TIME:
            log_message("info", "Wager race has NOT started yet.")
            data_cache = {"error": "Race not started yet."}
            return
        if now_utc > RACE_END_TIME:
            log_message("info", "Wager race has ENDED.")
            data_cache = {"error": "Race ended."}
            return

        # The API does not allow future dates. Clamp the "to" date if necessary.
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        valid_to_date = RACE_END_DATE if RACE_END_DATE <= today_str else today_str

        # Build payload as specified in the documentation.
        payload = {
            "apikey": UPGRADER_API_KEY,
            "from": RACE_START_DATE,
            "to": valid_to_date
        }

        log_message("info", f"[Attempting POST] {UPGRADER_API_ENDPOINT} with {json.dumps(payload)}")

        # Create a cloudscraper session (bypasses Cloudflare protection)
        scraper = cloudscraper.create_scraper()  # cloudscraper acts like requests.Session()

        # Set headers to mimic a common browser; these help bypass Cloudflare restrictions.
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36"),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Make the POST request with the JSON payload and custom headers.
        response = scraper.post(UPGRADER_API_ENDPOINT, json=payload, headers=headers, timeout=15)

        # Check for HTTP status code; if not 200, log error and update data cache.
        if response.status_code != 200:
            log_message("error", f"HTTP {response.status_code} => {response.text}")
            data_cache = {"error": f"HTTP {response.status_code} from Upgrader."}
            return

        # Parse the JSON response from Upgrader.
        resp_json = response.json()
        log_message("debug", f"Raw Upgrader API response: {json.dumps(resp_json)}")

        # If API indicates an error, capture and log it.
        if resp_json.get("error", True):
            msg = resp_json.get("msg", "Unknown API error")
            log_message("error", f"Upgrader API responded with an error: {msg}")
            data_cache = {"error": msg}
            return

        # Extract the summarized bets array and sort it by wager amount (descending).
        data_section = resp_json.get("data", {})
        summarized_bets = data_section.get("summarizedBets", [])
        sorted_bets = sorted(summarized_bets, key=lambda item: item.get("wager", 0), reverse=True)

        # Build dictionary for top 11 wagerers
        top_entries = {}
        for i, entry in enumerate(sorted_bets[:11], start=1):
            username = entry.get("user", {}).get("username", f"Player{i}")
            wager_cents = entry.get("wager", 0)
            # Convert cents to dollars and format with two decimals and commas.
            wager_str = f"${(wager_cents / 100):,.2f}"
            top_entries[f"top{i}"] = {"username": username, "wager": wager_str}

        # Fill in placeholders if there are fewer than 11 entries.
        for j in range(len(sorted_bets) + 1, 12):
            top_entries[f"top{j}"] = {"username": f"Player{j}", "wager": "$0.00"}

        data_cache = top_entries
        log_message("info", f"Data cache updated with {len(top_entries)} entries.")
    except Exception as ex:
        log_message("error", f"Exception during API call: {ex}")
        data_cache = {"error": str(ex)}

# ------------------------------------------------------------------------------------
# Schedule Data Fetching (Immediately and then every 90 seconds)
# ------------------------------------------------------------------------------------
def schedule_data_fetch():
    # Immediately fetch data on server boot
    fetch_data_from_api()
    # Then schedule periodic fetches every 90 seconds
    threading.Timer(90, schedule_data_fetch).start()

# ------------------------------------------------------------------------------------
# Flask Routes
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
# Start Scheduled Data Fetching and Flask Server
# ------------------------------------------------------------------------------------
schedule_data_fetch()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message("info", f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
