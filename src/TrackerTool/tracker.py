import json
from pathlib import Path

import subprocess
import re
import os
import glob
import time
import socket
from datetime import datetime
import json

import psutil
import requests
from getmac import get_mac_address
from dotenv import load_dotenv
import getpass

load_dotenv()

# =========================
# Config
# =========================

API_BASE_URL = os.getenv("API_BASE_URL", "https://tooltracker-afxj.onrender.com").rstrip("/")
LOG_DIR = os.path.join(os.getcwd(), "logs")

# Session-level (coarse) location tracking: capture ONCE per session (start)
# Default should be false for privacy; set true in .env when you have consent.
ENABLE_LOCATION_TRACKING = os.getenv("ENABLE_LOCATION_TRACKING", "false").lower() == "true"

# Public IP geolocation provider (no key). You can swap later if needed.
LOCATION_URL = os.getenv("LOCATION_URL", "https://ipapi.co/json/")

# =========================
# User ID helper
# =========================

def generate_username():
    pc_name = socket.gethostname()
    mac_address = get_mac_address()
    if not mac_address:
        raise Exception("Unable to retrieve the MAC address.")

    # ✅ override for testing multiple users
    forced = os.getenv("SET_USERNAME", "").strip()
    if forced:
        return f"{pc_name}_{forced}_{mac_address.replace(':', '_')}"

    # default = actual windows user
    win_user = getpass.getuser()
    return f"{pc_name}_{win_user}_{mac_address.replace(':', '_')}"



def load_cached_location():
    try:
        if not LOCATION_CACHE_FILE.exists():
            return None
        data = json.loads(LOCATION_CACHE_FILE.read_text(encoding="utf-8"))
        ts = float(data.get("_cached_at", 0))
        if time.time() - ts > LOCATION_CACHE_TTL_SECONDS:
            return None
        loc = data.get("location")
        return loc if isinstance(loc, dict) else None
    except Exception:
        return None


def save_cached_location(location: dict):
    try:
        payload = {"_cached_at": time.time(), "location": location}
        LOCATION_CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_location_from_provider(url: str, mapper):
    """Fetch and map provider JSON -> standardized dict"""
    res = requests.get(url, timeout=6)
    res.raise_for_status()
    data = res.json()
    loc = mapper(data)
    if loc and isinstance(loc, dict):
        return loc
    return None

# =========================
# Logging helpers
# =========================

def ensure_log_directory():
    if not os.path.exists(LOG_DIR):
        print(f"Creating log directory: {LOG_DIR}")
        os.makedirs(LOG_DIR)

def send_log_to_api(user_id, log_timestamp, log_content):
    data = {
        "user_id": user_id,
        "log_timestamp": log_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        "log_content": log_content
    }

    url = f"{API_BASE_URL}/add-log"
    try:
        res = requests.post(url, json=data, timeout=10)
        try:
            print("Log API Response:", res.json())
        except Exception:
            print("Log API Response (non-JSON):", res.status_code, res.text[:200])
    except requests.exceptions.RequestException as e:
        print(f"Error sending log data to API: {e}")

def store_log(user_id):
    """Send latest log file contents to API (if exists)."""
    try:
        log_files = sorted(
            glob.glob(os.path.join(LOG_DIR, "*.txt")) +
            glob.glob(os.path.join(LOG_DIR, "*.log")),
            key=os.path.getmtime,
            reverse=True
        )

        if not log_files:
            print(f"No log file found for user {user_id}.")
            return

        latest_log_file = log_files[0]

        with open(latest_log_file, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()

        send_log_to_api(user_id, datetime.now(), log_content)

    except Exception as e:
        print(f"Error handling log file: {e}")

# =========================
# Session location (coarse, once per session)
# =========================

def get_session_location():
    """
    Session location only:
    - Uses cache first (prevents rate limits)
    - Uses multiple providers as fallback
    - Returns dict or None
    """
    if not ENABLE_LOCATION_TRACKING:
        return None

    # ✅ 1) Use cached location if available (prevents 429)
    cached = load_cached_location()
    if cached:
        print("Location (cached):", cached)
        return cached

    # ✅ 2) Providers fallback chain
    providers = [
        # ipinfo.io (often works well; may rate-limit too)
        (
            "https://ipinfo.io/json",
            lambda d: {
                "ip": d.get("ip"),
                "city": d.get("city"),
                "region": d.get("region"),
                "country": d.get("country"),
            }
        ),

       
        (
            "http://ip-api.com/json",
            lambda d: {
                "ip": d.get("query"),
                "city": d.get("city"),
                "region": d.get("regionName"),
                "country": d.get("country"),
                "latitude": d.get("lat"),
                "longitude": d.get("lon"),
            }
        ),

        # ipwho.is (nice JSON, generally good free tier)
        (
            "https://ipwho.is/",
            lambda d: {
                "ip": d.get("ip"),
                "city": d.get("city"),
                "region": d.get("region"),
                "country": d.get("country"),
                "latitude": d.get("latitude"),
                "longitude": d.get("longitude"),
            } if d.get("success", True) else None
        ),
    ]

    for url, mapper in providers:
        try:
            loc = fetch_location_from_provider(url, mapper)
            if loc:
                print("Location fetched:", loc)
                save_cached_location(loc)  # ✅ cache it
                return loc
        except Exception as e:
            print(f"Location provider failed ({url}): {repr(e)}")

    # ✅ If all providers fail, return None safely
    return None



# =========================
# Session API
# =========================

def send_session_to_api(user_id, session_start, session_end, total_duration, location=None):
    data = {
        "user_id": user_id,
        "session_start": session_start.strftime('%Y-%m-%d %H:%M:%S'),
        "session_end": session_end.strftime('%Y-%m-%d %H:%M:%S'),
        "total_duration": total_duration,
        "location": location
    }

    url = f"{API_BASE_URL}/add-session"
    try:
        res = requests.post(url, json=data, timeout=10)
        try:
            print("Session API Response:", res.json())
        except Exception:
            print("Session API Response:", res.status_code, res.text[:200])
    except Exception as e:
        print("Session API Error:", e)



def log_session(user_id, session_start, session_end, location=None):
    total_duration_hours = (session_end - session_start).total_seconds() / 3600
    send_session_to_api(user_id, session_start, session_end, total_duration_hours, location=location)

# =========================
# Process monitor
# =========================

def is_esim_running():
    for process in psutil.process_iter(['name']):
        name = (process.info.get('name') or "").lower()
        if name == "esim.exe":
            return True
    return False

# =========================
# Crash detection via Windows Event Log
# =========================

def find_windows_crash_event(process_name="eSim.exe", lookback_seconds=600):
    ps = rf"""
$since = (Get-Date).AddSeconds(-{lookback_seconds})

# Collect candidate crash events for eSim.exe
$all = Get-WinEvent -FilterHashtable @{{
  LogName='Application';
  StartTime=$since
}} | Where-Object {{
  ($_.Id -in 1000,1001) -and ($_.Message -match '(?i){process_name}')
}} | Sort-Object TimeCreated -Descending

# Prefer Event ID 1000 if available, else take newest
$pick = ($all | Where-Object {{$_.Id -eq 1000}} | Select-Object -First 1)
if ($null -eq $pick) {{
  $pick = ($all | Select-Object -First 1)
}}

if ($null -eq $pick) {{ "" }} else {{ $pick | Select-Object TimeCreated, Id, ProviderName, Message | ConvertTo-Json -Compress }}
"""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stderr=subprocess.STDOUT,
            text=True
        ).strip()

        if not out:
            return None

        json_start = out.find("{")
        if json_start == -1:
            return None

        evt = json.loads(out[json_start:])
        msg = evt.get("Message", "") or ""

        crash = {
            "crash_time": (evt.get("TimeCreated") or ""),
            "event_id": int(evt.get("Id") or 0),
            "provider": evt.get("ProviderName") or "",
            "message": msg[:2000],
            "exception_code": "",
            "faulting_module": "",
        }

        # Event 1000: Application Error
        m = re.search(r"Faulting module name:\s*([^\s,]+)", msg, re.IGNORECASE)
        if m:
            crash["faulting_module"] = m.group(1).strip()

        m = re.search(r"Exception code:\s*(0x[0-9a-fA-F]+)", msg, re.IGNORECASE)
        if m:
            crash["exception_code"] = m.group(1).strip()

        # Event 1001: Windows Error Reporting (fallback)
        if not crash["faulting_module"]:
            m = re.search(r"^\s*P4:\s*([^\s\r\n]+)", msg, re.IGNORECASE | re.MULTILINE)
            if m:
                crash["faulting_module"] = m.group(1).strip()

        if not crash["exception_code"]:
            m = re.search(r"^\s*P8:\s*([0-9a-fA-F]+)", msg, re.IGNORECASE | re.MULTILINE)
            if m:
                crash["exception_code"] = "0x" + m.group(1).strip().lower()

        return crash

    except subprocess.CalledProcessError as e:
        print("PowerShell Get-WinEvent failed:", str(e)[:200])
        return None
    except Exception as e:
        print("Crash event parse failed:", e)
        return None

def normalize_ps_datetime(dt_value):
    """
    Converts PowerShell JSON datetime formats into 'YYYY-MM-DD HH:MM:SS'.
    Handles:
      - '/Date(1768410571967)/'
      - already-formatted strings
      - empty/None
    """
    if not dt_value:
        return None

    m = re.match(r"^/Date\((\d+)\)/$", str(dt_value).strip())
    if m:
        ms = int(m.group(1))
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

    return str(dt_value)

def send_crash_to_api(user_id, session_start, session_end, crash_info, location=None):
    crash_time_raw = crash_info.get("crash_time")
    crash_time_norm = normalize_ps_datetime(crash_time_raw)

    if not crash_time_norm and session_end:
        crash_time_norm = session_end.strftime('%Y-%m-%d %H:%M:%S')

    data = {
        "user_id": user_id,
        "session_start": session_start.strftime('%Y-%m-%d %H:%M:%S') if session_start else None,
        "session_end": session_end.strftime('%Y-%m-%d %H:%M:%S') if session_end else None,
        "crash_time": crash_time_norm,
        "event_id": crash_info.get("event_id", 0),
        "provider": crash_info.get("provider", ""),
        "exception_code": crash_info.get("exception_code", ""),
        "faulting_module": crash_info.get("faulting_module", ""),
        "message": crash_info.get("message", ""),
        "location": location  # NEW (dict or None)
    }

    url = f"{API_BASE_URL}/add-crash"
    try:
        res = requests.post(url, json=data, timeout=10)
        try:
            print("Crash API Response:", res.json())
        except Exception:
            print("Crash API Response (non-JSON):", res.status_code, res.text[:200])
    except requests.exceptions.RequestException as e:
        print(f"Error sending crash data to API: {e}")

# =========================
# Main loop
# =========================

def track_activity(user_id):
    session_start = None
    session_location = None  # NEW: capture once per session
    ensure_log_directory()

    print(f"Tracking started for user: {user_id}")
    print(f"API_BASE_URL: {API_BASE_URL}")
    print(f"ENABLE_LOCATION_TRACKING: {ENABLE_LOCATION_TRACKING}")

    try:
        while True:
            if is_esim_running():
                if session_start is None:
                    session_start = datetime.now()
                    session_location = get_session_location()
                    print("Session started at", session_start)
                    print("Session location:", session_location)

            else:
                if session_start:
                    session_end = datetime.now()

                    # Always log session end + upload session payload (with location)
                    log_session(user_id, session_start, session_end, location=session_location)

                    # Send latest log file (if any)
                    store_log(user_id)

                    # Give Windows time to write crash event
                    print("eSim stopped. Waiting 3s for Windows to write crash event...")
                    time.sleep(3)

                    # Check crash correlation
                    crash_info = find_windows_crash_event(
                        process_name="eSim.exe",
                        lookback_seconds=600
                    )
                    print("crash_info:", crash_info)

                    if crash_info:
                        print("Detected crash event for eSim.exe")
                        send_crash_to_api(
                            user_id=user_id,
                            session_start=session_start,
                            session_end=session_end,
                            crash_info=crash_info,
                            location=session_location
                        )

                    print(f"Session ended at {session_end}")
                    print(f"Duration: {session_end - session_start}")

                    # Reset for next session
                    session_start = None
                    session_location = None

            time.sleep(1)

    except KeyboardInterrupt:
        print("Tracking stopped.")

if __name__ == "__main__":
    user_id = os.getenv("TEST_USER_ID") or generate_username()
    track_activity(user_id)
