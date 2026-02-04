import subprocess
import re

import os
import glob
import time
import socket
from datetime import datetime

import psutil
import requests
from getmac import get_mac_address

from dotenv import load_dotenv
load_dotenv()

import getpass

def generate_username():
    pc_name = socket.gethostname()
    win_user = getpass.getuser()
    mac_address = get_mac_address()
    if mac_address:
        return f"{pc_name}_{win_user}_{mac_address.replace(':', '_')}"
    raise Exception("Unable to retrieve the MAC address.")


# ✅ Load API base URL from .env (fallback to Render if not set)
API_BASE_URL = os.getenv("API_BASE_URL", "https://tooltracker-afxj.onrender.com").rstrip("/")

# ✅ One LOG_DIR only
LOG_DIR = os.path.join(os.getcwd(), "logs")

def ensure_log_directory():
    if not os.path.exists(LOG_DIR):
        print(f"Creating log directory: {LOG_DIR}")
        os.makedirs(LOG_DIR)

def send_session_to_api(user_id, session_start, session_end, total_duration):
    data = {
        "user_id": user_id,
        "session_start": session_start.strftime('%Y-%m-%d %H:%M:%S'),
        "session_end": session_end.strftime('%Y-%m-%d %H:%M:%S'),
        "total_duration": total_duration

    }

    url = f"{API_BASE_URL}/add-session"
    try:
        res = requests.post(url, json=data, timeout=10)
        # If server returns HTML error page, .json() will fail
        try:
            print("Session API Response:", res.json())
        except Exception:
            print("Session API Response (non-JSON):", res.status_code, res.text[:200])

    except requests.exceptions.RequestException as e:
        print(f"Error sending session data to API: {e}")

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

def log_session(user_id, session_start, session_end):
    total_duration = (session_end - session_start).total_seconds() / 3600
    send_session_to_api(user_id, session_start, session_end, total_duration)

def store_log(user_id):
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


"""def store_log(user_id, session_start, session_end):
    
    Create a tracker-generated log for this session and send it to API
    
    log_content = (
        f"User: {user_id}\n"
        f"Session Start: {session_start}\n"
        f"Session End: {session_end}\n"
        f"Duration: {session_end - session_start}\n"
        f"Tracked via process monitoring (eSim running)\n"
    )

    send_log_to_api(user_id, datetime.now(), log_content)"""

def is_esim_running():
    for process in psutil.process_iter(['name']):
        name = (process.info.get('name') or "").lower()
        if name == "esim.exe":
            return True
    return False


def track_activity(user_id):
    session_start = None
    ensure_log_directory()

    print(f"Tracking started for user: {user_id}")
    print(f"API_BASE_URL: {API_BASE_URL}")

    try:
        while True:
            if is_esim_running():
                if session_start is None:
                    session_start = datetime.now()
                    print(f"Session started at {session_start}")

            else:
                if session_start:
                    session_end = datetime.now()

                    # Always log session end
                    log_session(user_id, session_start, session_end)
                    store_log(user_id)


                    # IMPORTANT: give Windows time to write the crash event
                    print("eSim stopped. Waiting 3s for Windows to write crash event...")
                    time.sleep(3)

                    # Check if it was a crash (Windows Event Log correlation)
                    crash_info = find_windows_crash_event(
                        process_name="eSim.exe",
                        lookback_seconds=600  # bigger window = more reliable
                    )
                    print("crash_info:", crash_info)

                    if crash_info:
                        print("Detected crash event for eSim.exe")
                        send_crash_to_api(user_id, session_start, session_end, crash_info)

                    print(f"Session ended at {session_end}")
                    print(f"Duration: {session_end - session_start}")
                    session_start = None

            time.sleep(1)

    except KeyboardInterrupt:
        print("Tracking stopped.")


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

        # locate JSON (in case PowerShell prints extra lines)
        json_start = out.find("{")
        if json_start == -1:
            return None

        import json
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

        # Event 1001: Windows Error Reporting
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

    # PowerShell JSON date format: /Date(XXXXXXXXXXXX)/
    m = re.match(r"^/Date\((\d+)\)/$", str(dt_value).strip())
    if m:
        ms = int(m.group(1))
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

    # Otherwise return as string (if it's already a normal datetime string)
    return str(dt_value)

def send_crash_to_api(user_id, session_start, session_end, crash_info):
    crash_time_raw = crash_info.get("crash_time")
    crash_time_norm = normalize_ps_datetime(crash_time_raw)

    # Fallback if crash_time is still missing
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



if __name__ == "__main__":
    user_id = os.getenv("TEST_USER_ID") or generate_username()
    track_activity(user_id)

