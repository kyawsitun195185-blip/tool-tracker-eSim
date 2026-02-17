import json
from pathlib import Path
import subprocess
import re
import os
import time
import socket
import platform
import asyncio
import requests
from datetime import datetime
from typing import Optional
import asyncio

from typing import Optional

from datetime import datetime, timedelta

import psutil
import requests
from getmac import get_mac_address
import getpass

# OCR (optional)
try:
    from PIL import ImageGrab
    import pytesseract
except Exception:
    ImageGrab = None
    pytesseract = None

import asyncio
from typing import Optional

async def _get_windows_location_async(timeout_seconds: int = 8, debug: bool = False) -> Optional[dict]:
    try:
        from winsdk.windows.devices.geolocation import Geolocator
        from winsdk.windows.devices.geolocation import GeolocationAccessStatus
    except Exception as e:
        if debug:
            print("[WINLOC] winsdk import failed:", repr(e))
        return None

    # 1) Ask Windows for access status (very useful for debugging)
    try:
        access = await Geolocator.request_access_async()
        if debug:
            print("[WINLOC] Access status:", access)

        # ALLOWED / DENIED / UNSPECIFIED
        if str(access).lower().endswith("denied") or str(access).lower().endswith("unspecified"):
            if debug:
                print("[WINLOC] Location disabled by user")

            return {
                "source": "windows_location",
                "status": "disabled",
                "latitude": None,
                "longitude": None,
                "accuracy_m": None,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    except Exception as e:
        if debug:
            print("[WINLOC] request_access_async failed:", repr(e))
        # Don't return yet; try geoposition anyway.

    # 2) Try to get a position
    try:
        geolocator = Geolocator()
        pos_task = geolocator.get_geoposition_async()
        geoposition = await asyncio.wait_for(pos_task, timeout=timeout_seconds)

        coord = geoposition.coordinate
        point = coord.point.position
        accuracy_m = getattr(coord, "accuracy", None)

        loc = {
            "source": "windows_location",
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "accuracy_m": float(accuracy_m) if accuracy_m is not None else None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # ✅ Reverse-geocode exact lat/lon -> city/region/country
        extra = reverse_geocode_osm(loc["latitude"], loc["longitude"], timeout=10, debug=debug)
        if extra:
            loc.update(extra)

        if debug:
            print("[WINLOC] Location OK:", loc)

        return loc

    except asyncio.TimeoutError:
        if debug:
            print("[WINLOC] Timed out waiting for geoposition.")
        return None
    except Exception as e:
        if debug:
            print("[WINLOC] get_geoposition_async failed:", repr(e))
        return None

def get_windows_location(timeout_seconds: int = 8, debug: bool = False) -> Optional[dict]:
    try:
        return asyncio.run(_get_windows_location_async(timeout_seconds=timeout_seconds, debug=debug))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_get_windows_location_async(timeout_seconds=timeout_seconds, debug=debug))
        finally:
            loop.close()
# =========================
# Config
# =========================
API_BASE_URL = "https://tool-tracker-esim-api.onrender.com".rstrip("/")
PROMPTED_LOCATION_THIS_SESSION = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_DIRS = [
    os.path.join(BASE_DIR, "logs"),                 # always same place
    os.path.expanduser(r"~\eSim-Workspace"),
    os.path.expandvars(r"%APPDATA%"),
    os.path.expandvars(r"%LOCALAPPDATA%"),
]

LOG_DIRS = [p for p in LOG_DIRS if p]  # remove empty

PROJECT_EXPLORER_PATH = os.path.join(os.path.expanduser("~"), "eSim-Workspace", ".projectExplorer")

ENABLE_LOCATION_TRACKING = True
ENABLE_OCR = False   # recommended off for Linux/mac unless you control display environment
ESIM_CONSOLE_BBOX = None  # set manually if you really want OCR

# For process matching (update for Ubuntu/mac if needed)
ESIM_PROCESS_NAMES = {"esim", "esim.exe"}

TOOL_KEYWORDS = {
    "nghdl": "[INFO]: NGHDL is called",
    "ngspice": "[INFO]: NGSPICE is called",
    "gtkwave": "[INFO]: GTKWave is called",
    "kicad": "[INFO]: KiCad is called",
    "iverilog": "[INFO]: Icarus Verilog is called",
    "python": "[INFO]: Python is called",
    "schematic": "[INFO]: Schematic converter is called",
    "converter": "[INFO]: Converter is called",
}

LOCATION_CACHE_FILE = Path(os.path.join(LOG_DIRS[0], "location_cache.json"))
LOCATION_CACHE_TTL_SECONDS = 10*60 # 1 day

LAST_EVENT_AT = {}
EVENT_COOLDOWN_SECONDS = 2


# =========================
# Helpers
# =========================
def ensure_log_directories():
    os.makedirs(LOG_DIRS[0], exist_ok=True)

def should_log_event(key: str):
    now = time.time()
    last = LAST_EVENT_AT.get(key, 0)
    if now - last < EVENT_COOLDOWN_SECONDS:
        return False
    LAST_EVENT_AT[key] = now
    return True

def reverse_geocode_osm(lat: float, lon: float, timeout: int = 10, debug: bool = False) -> dict:
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "format": "jsonv2",
        "lat": str(lat),
        "lon": str(lon),
        "zoom": "10",
        "addressdetails": "1",
        # This is recommended by many Nominatim deployments
        "email": "your_real_email@example.com",
    }
    headers = {
        # Make it look like a normal desktop client and identify your tool
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) eSim-Tool-Tracker/1.0",
        "Accept": "application/json",
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {}) if isinstance(data, dict) else {}

        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
        region = addr.get("state") or addr.get("region") or addr.get("county")
        country = addr.get("country")
        country_code = addr.get("country_code")

        out = {}
        if city: out["city"] = city
        if region: out["region"] = region
        if country: out["country"] = country
        if country_code: out["country_code"] = str(country_code).upper()

        if debug:
            print("[GEOCODE] Result:", out)
        return out

    except Exception as e:
        if debug:
            # Print response body if available (often explains why)
            try:
                print("[GEOCODE] HTTP status:", getattr(r, "status_code", None))
                print("[GEOCODE] Body:", getattr(r, "text", "")[:300])
            except Exception:
                pass
            print("[GEOCODE] Reverse geocode failed:", repr(e))
        return {}


import subprocess

import os

def prompt_enable_windows_location():
    print("[LOCATION] Windows location is OFF. Opening settings...")
    try:
        os.startfile("ms-settings:privacy-location")
    except Exception as e:
        print("[LOCATION] Failed to open settings:", e)


def generate_username():
    pc_name = socket.gethostname()
    os_user = getpass.getuser()
    mac = (get_mac_address() or "no_mac").replace(":", "_")
    return f"{pc_name}_{os_user}_{mac}"

def tracker_log_path(user_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-\.]", "_", user_id)
    return os.path.join(LOG_DIRS[0], f"tracker_{safe}.log")

def append_tracker_log(user_id: str, msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}".rstrip()
    with open(tracker_log_path(user_id), "a", encoding="utf-8", errors="ignore") as f:
        f.write(line + "\n")
    print(line)

def debug_esim_processes():
    hits = []
    for p in psutil.process_iter(["pid","name"]):
        try:
            name = (p.info.get("name") or "")
            if "esim" in name.lower():
                hits.append((p.info["pid"], name))
        except Exception:
            pass
    return hits

# =========================
# HTTP helper
# =========================
def post_with_retry(url, payload, timeout=30, retries=3, backoff=2):
    last_err = None
    for i in range(retries):
        try:
            res = requests.post(url, json=payload, timeout=timeout)

            # If server says duplicate, treat as success (until server is fixed)
            if res.status_code >= 400:
                try:
                    j = res.json()
                    msg = str(j.get("error", "")).lower()
                    if "duplicate key value" in msg and "sessions_user_start_end_uniq" in msg:
                        print("Duplicate session on server (already stored).")
                        return res
                except Exception:
                    pass

            return res

        except requests.exceptions.ReadTimeout as e:
            last_err = e
            print(f"[POST retry {i+1}/{retries}] ReadTimeout — server may have stored it already.")
            time.sleep(backoff ** i)

        except requests.exceptions.RequestException as e:
            last_err = e
            print(f"[POST retry {i+1}/{retries}] {url} failed: {e}")
            time.sleep(backoff ** i)

    raise last_err



# =========================
# Process Monitoring
# =========================
def snapshot_processes():
    """
    Returns dict {pid: (name_lower, create_time, cmdline_str)}.
    cmdline may be empty if AccessDenied.
    """
    procs = {}
    for p in psutil.process_iter(["pid", "name", "create_time", "cmdline"]):
        try:
            pid = p.info["pid"]
            name = (p.info.get("name") or "").lower()
            ctime = float(p.info.get("create_time") or 0.0)

            cmdline = ""
            cl = p.info.get("cmdline")
            if isinstance(cl, list):
                cmdline = " ".join(cl)
            elif isinstance(cl, str):
                cmdline = cl

            procs[pid] = (name, ctime, cmdline)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return procs

def detect_new_processes(prev_snapshot: dict, cur_snapshot: dict):
    events = []
    for pid, (name, ctime, cmdline) in cur_snapshot.items():
        if pid not in prev_snapshot:
            events.append((pid, name, cmdline))
    return events

def classify_process(proc_name: str, cmdline: str) -> str | None:
    s = (proc_name + " " + (cmdline or "")).lower()
    for key, msg in TOOL_KEYWORDS.items():
        if key in s:
            return msg
    return None

def is_esim_running():
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if "esim" in name:   # instead of exact match
            return True
    return False



# =========================
# Project Explorer (optional)
# =========================
def load_project_explorer(path: str) -> dict:
    try:
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def detect_new_projects(prev: dict, cur: dict) -> list[str]:
    prev_keys = set(prev.keys()) if isinstance(prev, dict) else set()
    cur_keys = set(cur.keys()) if isinstance(cur, dict) else set()
    return sorted(list(cur_keys - prev_keys))

def get_project_name_from_path(project_path: str) -> str:
    try:
        return os.path.basename(project_path.rstrip("\\/")) or project_path
    except Exception:
        return project_path


# =========================
# Location
# =========================
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
    res = requests.get(url, timeout=6)
    res.raise_for_status()
    data = res.json()
    loc = mapper(data)
    return loc if isinstance(loc, dict) else None

def get_session_location():
    global PROMPTED_LOCATION_THIS_SESSION

    if not ENABLE_LOCATION_TRACKING:
        return None

    os_is_windows = platform.system().lower() == "windows"
    cached = load_cached_location()

    if os_is_windows:
        loc = get_windows_location(timeout_seconds=8, debug=False)

        # 🟢 Windows location working
        if loc and loc.get("latitude") is not None:
            print("Location fetched (Windows):", loc)
            save_cached_location(loc)
            PROMPTED_LOCATION_THIS_SESSION = False
            return loc

        # 🔴 Windows location disabled
        if loc and loc.get("status") == "disabled":
            print("[LOCATION] Windows location disabled → using IP fallback")

            # Prompt only once per session
            if not PROMPTED_LOCATION_THIS_SESSION:
                prompt_enable_windows_location()
                PROMPTED_LOCATION_THIS_SESSION = True

            cached = None  # ignore old windows cache

        # ❌ Windows unavailable (timeout/error)
        if loc is None:
            print("[LOCATION] Windows location unavailable → using IP fallback")

            if not PROMPTED_LOCATION_THIS_SESSION:
                prompt_enable_windows_location()
                PROMPTED_LOCATION_THIS_SESSION = True

    cached = None

    # 🌍 Use cached IP only (never cached windows when OFF)
    if cached and cached.get("source") != "windows_location":
        print("Location (cached IP):", cached)
        return cached

    # 🌍 IP fallback
    providers = [
        ("https://ipinfo.io/json",
         lambda d: {
             "source": "ip_location",
             "ip": d.get("ip"),
             "city": d.get("city"),
             "region": d.get("region"),
             "country": d.get("country"),
             "latitude": float(d["loc"].split(",")[0]) if d.get("loc") and "," in d.get("loc") else None,
             "longitude": float(d["loc"].split(",")[1]) if d.get("loc") and "," in d.get("loc") else None,
         }),
    ]

    for url, mapper in providers:
        try:
            loc = fetch_location_from_provider(url, mapper)
            if loc:
                print("Location fetched (IP):", loc)
                save_cached_location(loc)
                return loc
        except Exception as e:
            print(f"Location provider failed ({url}): {repr(e)}")

    return None

# =========================
# API calls
# =========================
def send_log_to_api(user_id, log_timestamp, log_content):
    url = f"{API_BASE_URL}/add-log"
    payload = {
        "user_id": user_id,
        "log_timestamp": log_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "log_content": log_content
    }
    try:
        res = post_with_retry(url, payload, timeout=30, retries=3, backoff=2)
        try:
            print("Log API Response:", res.status_code, res.json())
        except Exception:
            print("Log API Response:", res.status_code, res.text[:300])
    except Exception as e:
        print("Log API Error: all retries failed:", e)

def store_log(user_id):
    path = tracker_log_path(user_id)
    if not os.path.isfile(path):
        print(f"No tracker log file found for user {user_id}.")
        return

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        log_content = f.read()

    if not log_content.strip():
        print(f"Tracker log is empty for user {user_id}.")
        return

    send_log_to_api(user_id, datetime.now(), log_content)

def send_session_to_api(user_id, session_start, session_end, total_duration_hours, location=None):
    url = f"{API_BASE_URL}/add-session"
    payload = {
        "user_id": user_id,
        "session_start": session_start.strftime("%Y-%m-%d %H:%M:%S"),
        "session_end": session_end.strftime("%Y-%m-%d %H:%M:%S"),
        "total_duration": total_duration_hours,
        "location": location
    }
    try:
        res = post_with_retry(url, payload, timeout=30, retries=3, backoff=2)
        try:
            print("Session API Response:", res.status_code, res.json())
        except Exception:
            print("Session API Response:", res.status_code, res.text[:300])
    except Exception as e:
        print("Session API Error: all retries failed:", e)

def log_session(user_id, session_start, session_end, location=None):
    total_duration_hours = (session_end - session_start).total_seconds() / 3600
    send_session_to_api(user_id, session_start, session_end, total_duration_hours, location=location)

def send_crash_to_api(user_id, session_start, session_end, crash_info, location=None):
    url = f"{API_BASE_URL}/add-crash"
    payload = {
        "user_id": user_id,
        "session_start": session_start.strftime("%Y-%m-%d %H:%M:%S"),
        "session_end": session_end.strftime("%Y-%m-%d %H:%M:%S"),
        "crash_time": crash_info.get("crash_time"),
        "event_id": crash_info.get("event_id", 0),
        "provider": crash_info.get("provider", ""),
        "exception_code": crash_info.get("exception_code", ""),
        "faulting_module": crash_info.get("faulting_module", ""),
        "message": crash_info.get("message", ""),
        "location": location
    }
    try:
        res = post_with_retry(url, payload, timeout=30, retries=3, backoff=2)
        print("Crash API Response:", res.status_code, getattr(res, "text", "")[:200])
    except Exception as e:
        print("Crash API Error:", e)


# =========================
# Crash detection (Windows/Linux/macOS)
# =========================
def find_windows_crash_event(process_name="eSim.exe", lookback_seconds=600):
    ps = rf"""
$since = (Get-Date).AddSeconds(-{lookback_seconds})
$all = Get-WinEvent -FilterHashtable @{{ 
  LogName='Application';
  StartTime=$since
}} | Where-Object {{
  ($_.Id -in 1000,1001) -and ($_.Message -match '(?i){process_name}')
}} | Sort-Object TimeCreated -Descending

$pick = ($all | Where-Object {{ $_.Id -eq 1000 }} | Select-Object -First 1)
if ($null -eq $pick) {{
  $pick = ($all | Select-Object -First 1)
}}

if ($null -eq $pick) {{
  ""
}} else {{
  $obj = [PSCustomObject]@{{
    TimeCreated  = $pick.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
    Id           = $pick.Id
    ProviderName = $pick.ProviderName
    Message      = $pick.Message
  }}
  $obj | ConvertTo-Json -Compress
}}
"""

    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stderr=subprocess.STDOUT,
            text=True,
            errors="ignore"
        ).strip()

        if not out:
            return None

        json_start = out.find("{")
        if json_start == -1:
            return None

        evt = json.loads(out[json_start:])
        msg = evt.get("Message", "") or ""

        crash = {
            "crash_time": (evt.get("TimeCreated") or ""),  # now "YYYY-MM-DD HH:MM:SS"
            "event_id": int(evt.get("Id") or 0),
            "provider": evt.get("ProviderName") or "",
            "message": msg[:2000],
            "exception_code": "",
            "faulting_module": "",
        }

        m = re.search(r"Faulting module name:\s*([^\s,]+)", msg, re.IGNORECASE)
        if m:
            crash["faulting_module"] = m.group(1).strip()

        m = re.search(r"Exception code:\s*(0x[0-9a-fA-F]+)", msg, re.IGNORECASE)
        if m:
            crash["exception_code"] = m.group(1).strip()

        return crash
    except Exception:
        return None


def find_linux_crash(process_hint="esim", lookback_seconds=600):
    since = (datetime.now() - timedelta(seconds=lookback_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    cmd = ["journalctl", "--since", since, "-o", "short-iso", "--no-pager"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, errors="ignore")
    except Exception:
        return None

    lines = []
    ph = process_hint.lower()
    for line in out.splitlines():
        low = line.lower()
        if ph in low and any(k in low for k in ["segfault", "core dumped", "crash", "abrt", "fatal", "assert"]):
            lines.append(line)

    if not lines:
        return None

    msg = "\n".join(lines[-30:])
    return {
        "crash_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": "journalctl",
        "event_id": 0,
        "exception_code": "",
        "faulting_module": "",
        "message": msg[:2000],
    }

def find_macos_crash(process_hint="eSim", lookback_seconds=600):
    start = datetime.now() - timedelta(seconds=lookback_seconds)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    predicate = f'process == "ReportCrash" AND eventMessage CONTAINS[c] "{process_hint}"'
    cmd = ["log", "show", "--style", "syslog", "--start", start_str, "--predicate", predicate]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, errors="ignore")
    except Exception:
        return None

    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return None

    msg = "\n".join(lines[-30:])
    return {
        "crash_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": "macOS log",
        "event_id": 0,
        "exception_code": "",
        "faulting_module": "",
        "message": msg[:2000],
    }

def detect_crash_cross_platform(process_hint="esim", lookback_seconds=600):
    os_name = platform.system().lower()
    if os_name == "windows":
        return find_windows_crash_event(process_name="eSim.exe", lookback_seconds=lookback_seconds)
    if os_name == "linux":
        return find_linux_crash(process_hint=process_hint, lookback_seconds=lookback_seconds)
    if os_name == "darwin":
        return find_macos_crash(process_hint=process_hint, lookback_seconds=lookback_seconds)
    return None

if platform.system().lower() == "windows":
    test_loc = get_windows_location()
    print("Windows location test:", test_loc)

# =========================
# Main loop
# =========================
def track_activity(user_id):
    ensure_log_directories()

    session_start = None
    session_location = None

    prev_snapshot = snapshot_processes()
    prev_proj_map = load_project_explorer(PROJECT_EXPLORER_PATH)

    print(f"Tracking started for user: {user_id}")
    print(f"API_BASE_URL: {API_BASE_URL}")
    print(f"OS: {platform.system()}")

    try:
        while True:
            running = is_esim_running()

            # Session start
            if running and session_start is None:
                session_start = datetime.now()
                session_location = get_session_location()

                append_tracker_log(user_id, "eSim Started......")
                append_tracker_log(user_id, f"[INFO]: Workspace : {os.path.join(os.path.expanduser('~'), 'eSim-Workspace')}")
                prev_snapshot = snapshot_processes()

            # Detect new processes (minimize-safe)
            cur_snapshot = snapshot_processes()
            if running:
                print("eSim processes:", debug_esim_processes())
                for pid, name, cmdline in detect_new_processes(prev_snapshot, cur_snapshot):
                    action = classify_process(name, cmdline)
                    if action and should_log_event(action):
                        append_tracker_log(user_id, action)
                        if cmdline:
                            append_tracker_log(user_id, f"[CMD]: {cmdline}")

                # Detect new projects via .projectExplorer
                cur_proj_map = load_project_explorer(PROJECT_EXPLORER_PATH)
                for proj_path in detect_new_projects(prev_proj_map, cur_proj_map):
                    proj_name = get_project_name_from_path(proj_path)
                    append_tracker_log(user_id, f"[INFO]: New project created : {proj_name}")
                    append_tracker_log(user_id, f"[INFO]: Current project is : {proj_path}")
                prev_proj_map = cur_proj_map

            prev_snapshot = cur_snapshot

            # Session end
            if (not running) and session_start is not None:
                session_end = datetime.now()
                append_tracker_log(user_id, "eSim Stopped.")
                log_session(user_id, session_start, session_end, location=session_location)
                store_log(user_id)

                time.sleep(2)  # allow OS to write crash logs
                crash_info = detect_crash_cross_platform(process_hint="esim", lookback_seconds=600)
                print("crash_info:", crash_info)
                if crash_info:
                    send_crash_to_api(user_id, session_start, session_end, crash_info, location=session_location)

                # reset
                session_start = None
                session_location = None
                prev_snapshot = snapshot_processes()

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("Tracking stopped.")


if __name__ == "__main__":
    user_id = os.getenv("TEST_USER_ID") or generate_username()
    track_activity(user_id)
