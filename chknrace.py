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
# CONFIGURATION / CONSTANTS
# ------------------------------------------------------------------------------------
UPGRADER_API_KEY = "05204562-cd13-4495-9141-f016f5d32f26"  # Must remain under 100 chars

# The doc says the POST endpoint is "/affiliate/creator/get-stats"
# We'll try that EXACT path, but if we get 405 we also try a trailing slash fallback.
MAIN_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats"
TRAILING_SLASH_ENDPOINT = "https://upgrader.com/affiliate/creator/get-stats/"

# Race window from March 13 at 3 AM to March 21 at 3 AM (UTC)
RACE_START_TIME = datetime(2025, 3, 13, 3, 0, 0)
RACE_END_TIME   = datetime(2025, 3, 21, 3, 0, 0)

RACE_START_DATE = "2025-03-13"
RACE_END_DATE   = "2025-03-21"

# Data cache for scoreboard
data_cache = {}

# ------------------------------------------------------------------------------------
# Create a persistent session with typical browser headers, including JSON accept
# and content-type so the server knows we are sending/expecting JSON.
# ------------------------------------------------------------------------------------
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
})

def log_message(level, message):
    """
    Simple helper to log messages with timestamps.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] [{level.upper()}]: {message}")

def fetch_data_from_endpoint(url, payload, attempt, max_retries):
    """
    Make a POST request to a given URL with a JSON payload.
    We do a random sleep + backoff if there's a server error or 405.
    Returns a tuple: (success_bool, response_or_error_msg)
    """
    # Random short sleep to mimic user pacing
    time.sleep(random.uniform(0.2, 1.0))

    log_message("info", f"[Attempt {attempt}/{max_retries}] Requesting {url} with payload: {payload}")
    try:
        response = session.post(url, json=payload, timeout=15)
    except requests.exceptions.RequestException as exc:
        log_message("error", f"Network Exception on attempt {attempt}: {exc}")
        return False, f"Network error: {exc}"

    # If server responded:
    if response.status_code == 200:
        return True, response
    else:
        # e.g. 405 => Method Not Allowed, 5xx => server error
        log_message("error", f"HTTP {response.status_code} => {response.text[:300]}")
        return False, response

def fetch_data_from_api():
    """
    Attempt to fetch data from Upgrader, matching the doc's "POST" approach.
    If we get 405 at the standard path, try the trailing slash path next.
    """
    global data_cache

    now_utc = datetime.utcnow()

    # Hasn't started or ended?
    if now_utc < RACE_START_TIME:
        log_message("info", "Race has NOT started yet.")
        data_cache = {"error": "Race has not started yet."}
        return

    if now_utc > RACE_END_TIME:
        log_message("info", "Race has ENDED.")
        data_cache = {"error": "Race has ended."}
        return

    # Payload
    payload = {
        "apikey": UPGRADER_API_KEY,
        "from": RACE_START_DATE,
        "to":   RACE_END_DATE
    }

    max_retries = 3
    attempt = 0
    # We'll first try the main endpoint. If 405, fallback to trailing slash.
    used_trailing_slash = False

    while attempt < max_retries:
        attempt += 1

        ok, resp_or_err = fetch_data_from_endpoint(MAIN_ENDPOINT, payload, attempt, max_retries)
        if ok:
            # We got a 200. Parse & store scoreboard
            return handle_upgrader_response(resp_or_err)
        else:
            # If the status_code is 405 or specifically if we see "405 Not Allowed"
            if isinstance(resp_or_err, requests.Response) and resp_or_err.status_code == 405:
                log_message("warning", "We got 405 at the main path. Trying trailing slash endpoint.")
                used_trailing_slash = True
                break  # We'll drop out & do the trailing slash approach

            # If it's 4xx or 5xx, do a backoff unless we've run out of tries
            if isinstance(resp_or_err, requests.Response):
                status = resp_or_err.status_code
                if 400 <= status < 500 and status != 405:
                    # Some other client error => stop
                    data_cache = {"error": f"Client Error {status} from Upgrader."}
                    return
                else:
                    # 5xx or 405 => keep going or error out if last attempt
                    if attempt < max_retries:
                        backoff_sec = 5 + attempt * 2
                        log_message("warning", f"Server or method error {status}, retrying in {backoff_sec}s...")
                        time.sleep(backoff_sec)
                    else:
                        data_cache = {"error": f"Stopped after {max_retries} attempts (HTTP {status})."}
                        return
            else:
                # Some network error
                if attempt < max_retries:
                    backoff_sec = 5 + attempt * 2
                    log_message("warning", f"Retrying in {backoff_sec}s after network error…")
                    time.sleep(backoff_sec)
                else:
                    data_cache = {"error": resp_or_err}
                    return

    # If we got here, we either gave up or we need to try trailing slash if we got 405
    if used_trailing_slash:
        # Attempt the trailing slash route
        log_message("info", "Now trying the trailing slash endpoint: /affiliate/creator/get-stats/")
        attempt_ts = 0
        while attempt_ts < max_retries:
            attempt_ts += 1
            ok_ts, resp_or_err_ts = fetch_data_from_endpoint(TRAILING_SLASH_ENDPOINT, payload, attempt_ts, max_retries)
            if ok_ts:
                return handle_upgrader_response(resp_or_err_ts)
            else:
                if isinstance(resp_or_err_ts, requests.Response):
                    status = resp_or_err_ts.status_code
                    if 400 <= status < 500:
                        # Probably won't fix itself
                        data_cache = {"error": f"Client Error {status} from trailing slash endpoint."}
                        return
                    else:
                        # 5xx => backoff or final fail
                        if attempt_ts < max_retries:
                            backoff_sec = 5 + attempt_ts * 2
                            log_message("warning", f"Server error {status} on trailing slash. Retrying in {backoff_sec}s…")
                            time.sleep(backoff_sec)
                        else:
                            data_cache = {"error": f"Stopped after {max_retries} attempts (HTTP {status})."}
                            return
                else:
                    # Some non-Response error
                    if attempt_ts < max_retries:
                        backoff_sec = 5 + attempt_ts * 2
                        log_message("warning", f"Retrying in {backoff_sec}s after net error on trailing slash…")
                        time.sleep(backoff_sec)
                    else:
                        data_cache = {"error": resp_or_err_ts}
                        return

    # If we never used trailing slash or everything else failed, finalize an error if not set
    if not data_cache:
        data_cache = {"error": "Failed to retrieve data after multiple attempts."}


def handle_upgrader_response(response):
    """
    Takes a successful (status=200) Response object from Upgrader,
    parses the JSON, updates data_cache with scoreboard.
    """
    global data_cache

    try:
        resp_json = response.json()
        log_message("debug", f"Raw API response after success: {json.dumps(resp_json)}")

        # If "error" is True, the API itself is returning an error
        if resp_json.get("error", True):
            msg = resp_json.get("msg", "Unknown error from Upgrader")
            log_message("error", f"Upgrader API says: {msg}")
            data_cache = {"error": msg}
            return

        data_section = resp_json.get("data", {})
        summarized_bets = data_section.get("summarizedBets", [])

        # Sort by 'wager' desc
        sorted_bets = sorted(summarized_bets, key=lambda x: x.get("wager", 0), reverse=True)

        scoreboard = {}
        for i, entry in enumerate(sorted_bets[:11], start=1):
            cents_val = entry.get("wager", 0)
            user_name = entry.get("user", {}).get("username", f"Player{i}")
            scoreboard[f"top{i}"] = {
                "username": user_name,
                "wager": f"${(cents_val / 100):,.2f}"
            }
        # Fill placeholders if fewer than 11
        for idx in range(len(sorted_bets[:11]) + 1, 12):
            scoreboard[f"top{idx}"] = {
                "username": f"Player{idx}",
                "wager": "$0.00"
            }

        data_cache = scoreboard
        log_message("info", f"Data cache updated with {len(scoreboard)} entries.")
    except Exception as exc:
        log_message("error", f"Exception parsing Upgrader response JSON: {exc}")
        data_cache = {"error": f"Exception parsing JSON: {exc}"}


def schedule_data_fetch():
    """
    Schedules the data fetch on server start, then every 90 seconds.
    """
    fetch_data_from_api()
    threading.Timer(90, schedule_data_fetch).start()

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

if __name__ == "__main__":
    schedule_data_fetch()
    port = int(os.getenv("PORT", 8080))
    log_message("info", f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
