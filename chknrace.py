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
# Upgrader Creator API key and endpoint as per documentation.
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"
UPGRADER_API_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"

# Race window dates (the payload "from" and "to")
RACE_START_DATE = "2025-03-13"  # YYYY-MM-DD format
RACE_END_DATE   = "2025-03-21"  # YYYY-MM-DD format

# Fixed times for race window (3:00 AM UTC)
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

# Global cache for API data
data_cache = {}

# ------------------------------------------------------------------------------------
# Logging Utility Function
# ------------------------------------------------------------------------------------
def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# ------------------------------------------------------------------------------------
# Fetch Data from Upgrader API with Extensive Logging and Cloudflare Bypass
# ------------------------------------------------------------------------------------
def fetch_data_from_api():
    global data_cache
    try:
        request_start_time = time.time()
        now_utc = datetime.utcnow()
        log_message("debug", f"Current UTC time: {now_utc}")

        # Check race window status.
        if now_utc < RACE_START_TIME:
            log_message("info", "Wager race has NOT started yet.")
            data_cache = {"error": "Race not started yet."}
            return
        if now_utc > RACE_END_TIME:
            log_message("info", "Wager race has ENDED.")
            data_cache = {"error": "Race ended."}
            return

        # Ensure the 'to' date does not exceed today's date (API does not allow future dates)
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        valid_to_date = RACE_END_DATE if RACE_END_DATE <= today_str else today_str

        # Build the JSON payload as specified in the API documentation.
        payload = {
            "apikey": UPGRADER_API_KEY,
            "from": RACE_START_DATE,
            "to": valid_to_date
        }
        log_message("info", f"[Attempting POST] {UPGRADER_API_ENDPOINT} with payload: {json.dumps(payload)}")

        # Create a cloudscraper session to bypass Cloudflare protection.
        scraper = cloudscraper.create_scraper()

        # Define custom headers to mimic a real browser.
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/90.0.4430.93 Safari/537.36"),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        log_message("debug", f"Request headers: {headers}")

        # Make the POST request with a timeout.
        response = scraper.post(UPGRADER_API_ENDPOINT, json=payload, headers=headers, timeout=15)
        duration = time.time() - request_start_time
        log_message("debug", f"Request completed in {duration:.2f} seconds with status code {response.status_code}")

        # Log response headers and a snippet of the response text.
        log_message("debug", f"Response headers: {response.headers}")
        log_message("debug", f"Response text (first 500 chars): {response.text[:500]}")

        # If the response is not OK, log and update error state.
        if response.status_code != 200:
            log_message("error", f"HTTP {response.status_code} error received: {response.text}")
            data_cache = {"error": f"HTTP {response.status_code} error from Upgrader."}
            return

        # Parse the JSON response.
        resp_json = response.json()
        log_message("debug", f"Response JSON: {json.dumps(resp_json)}")

        # Check if API returned an error.
        if resp_json.get("error", True):
            msg = resp_json.get("msg", "Unknown API error")
            log_message("error", f"API error: {msg}")
            data_cache = {"error": msg}
            return

        # Extract and sort the summarized bets array (by wager in descending order).
        data_section = resp_json.get("data", {})
        summarized_bets = data_section.get("summarizedBets", [])
        sorted_bets = sorted(summarized_bets, key=lambda item: item.get("wager", 0), reverse=True)

        # Build dictionary for the top 11 wagerers.
        top_entries = {}
        for i, entry in enumerate(sorted_bets[:11], start=1):
            username = entry.get("user", {}).get("username", f"Player{i}")
            wager_cents = entry.get("wager", 0)
            wager_str = f"${(wager_cents / 100):,.2f}"
            top_entries[f"top{i}"] = {"username": username, "wager": wager_str}
            log_message("debug", f"Top {i}: {username} with wager {wager_str}")

        # Fill in placeholders if there are fewer than 11 entries.
        for j in range(len(sorted_bets) + 1, 12):
            top_entries[f"top{j}"] = {"username": f"Player{j}", "wager": "$0.00"}
            log_message("debug", f"Top {j}: Placeholder set to Player{j} with wager $0.00")

        # Update the global data cache.
        data_cache = top_entries
        log_message("info", f"Data cache updated with {len(top_entries)} entries.")
    except Exception as ex:
        log_message("error", f"Exception during API call: {ex}")
        data_cache = {"error": str(ex)}

# ------------------------------------------------------------------------------------
# Schedule Data Fetching Immediately and Every 90 Seconds
# ------------------------------------------------------------------------------------
def schedule_data_fetch():
    fetch_data_from_api()
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
