import os
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from db import fetch_all, fetch_one, execute

load_dotenv()

# ----------------------------
# App + Static Frontend
# ----------------------------
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")

# CORS
origins = os.getenv("CORS_ORIGINS", "*")
if origins != "*":
    origins = [o.strip() for o in origins.split(",") if o.strip()]
CORS(app, resources={r"/*": {"origins": origins}})

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")


# ----------------------------
# Auth
# ----------------------------
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ----------------------------
# JSON Safe Helpers
# ----------------------------
def td_to_hms(td):
    if td is None:
        return None
    if isinstance(td, timedelta):
        total_seconds = int(td.total_seconds())
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    return td

def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(obj, timedelta):
        return td_to_hms(obj)
    return obj


def parse_dt(s: str):
    """Accepts 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'"""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def dt_range_default():
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=30)
    return from_dt, to_dt

def get_from_to():
    dt_from = parse_dt(request.args.get("from", "").strip())
    dt_to = parse_dt(request.args.get("to", "").strip())
    if not dt_from or not dt_to:
        return dt_range_default()
    return dt_from, dt_to


# ----------------------------
# Frontend Routes
# ----------------------------
@app.get("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ----------------------------
# Admin: Users
# ----------------------------
@app.get("/admin/users")
@require_admin
def admin_users():
    sql = """
    SELECT DISTINCT user_id FROM (
        SELECT user_id FROM sessions
        UNION
        SELECT user_id FROM logs
        UNION
        SELECT user_id FROM crashes
    ) t
    ORDER BY user_id;
    """
    rows = fetch_all(sql)
    return jsonify([r["user_id"] for r in rows])


# ----------------------------
# Admin: Overview
# ----------------------------
@app.get("/admin/overview")
@require_admin
def admin_overview():
    since = datetime.now() - timedelta(days=7)

    users_count = fetch_one("""
        SELECT COUNT(DISTINCT user_id) AS c FROM (
            SELECT user_id FROM sessions
            UNION
            SELECT user_id FROM crashes
            UNION
            SELECT user_id FROM logs
        ) t;
    """)["c"]

    sessions_7d = fetch_one("""
        SELECT COUNT(*) AS c
        FROM sessions
        WHERE session_start >= %s;
    """, [since])["c"]

    crashes_7d = fetch_one("""
        SELECT COUNT(*) AS c
        FROM crashes
        WHERE crash_time >= %s;
    """, [since])["c"]

    latest_sessions = fetch_all("""
        SELECT user_id, session_start, session_end, total_duration
        FROM sessions
        ORDER BY session_start DESC
        LIMIT 8;
    """)

    latest_crashes = fetch_all("""
        SELECT crash_id, user_id, crash_time, exception_code, faulting_module, event_id
        FROM crashes
        ORDER BY crash_time DESC
        LIMIT 8;
    """)

    return jsonify(make_json_safe({
        "users_count": users_count,
        "sessions_7d": sessions_7d,
        "crashes_7d": crashes_7d,
        "latest_sessions": latest_sessions,
        "latest_crashes": latest_crashes,
    }))


# ----------------------------
# Admin: Sessions
# ----------------------------
@app.get("/admin/sessions")
@require_admin
def admin_sessions():
    user = request.args.get("user", "").strip()
    from_s = request.args.get("from", "").strip()
    to_s = request.args.get("to", "").strip()
    limit = int(request.args.get("limit", "200"))

    dt_from = parse_dt(from_s)
    dt_to = parse_dt(to_s)

    where = []
    params = []

    if user:
        where.append("user_id = %s")
        params.append(user)
    if dt_from:
        where.append("session_start >= %s")
        params.append(dt_from)
    if dt_to:
        where.append("session_start <= %s")
        params.append(dt_to)

    w = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
    SELECT session_id, user_id, session_start, session_end, total_duration
    FROM sessions
    {w}
    ORDER BY session_start DESC
    LIMIT %s;
    """
    params.append(limit)

    return jsonify(make_json_safe(fetch_all(sql, params)))


@app.delete("/admin/sessions/<int:session_id>")
@require_admin
def admin_delete_session(session_id: int):
    n = execute("DELETE FROM sessions WHERE session_id = %s;", [session_id])
    if n == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "Session deleted"})


# ----------------------------
# Admin: Logs
# ----------------------------
@app.get("/admin/logs")
@require_admin
def admin_logs():
    user = request.args.get("user", "").strip()
    limit = int(request.args.get("limit", "200"))

    where = ""
    params = []
    if user:
        where = "WHERE user_id=%s"
        params.append(user)

    sql = f"""
    SELECT log_id, user_id, log_timestamp, log_content
    FROM logs
    {where}
    ORDER BY log_timestamp DESC
    LIMIT %s;
    """
    params.append(limit)

    return jsonify(make_json_safe(fetch_all(sql, params)))


# ----------------------------
# Admin: Crashes (raw + summary)
# ----------------------------
@app.get("/admin/crashes")
@require_admin
def admin_crashes():
    user = request.args.get("user", "").strip()
    exc = request.args.get("exception_code", "").strip()
    mod = request.args.get("faulting_module", "").strip()
    q = request.args.get("q", "").strip().lower()
    limit = int(request.args.get("limit", "500"))

    where = []
    params = []

    if user:
        where.append("user_id = %s")
        params.append(user)
    if exc:
        where.append("exception_code = %s")
        params.append(exc)
    if mod:
        where.append("faulting_module = %s")
        params.append(mod)

    if q:
        where.append("""
          (LOWER(COALESCE(message,'')) LIKE %s
           OR LOWER(COALESCE(faulting_module,'')) LIKE %s
           OR LOWER(COALESCE(exception_code,'')) LIKE %s)
        """)
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    w = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
    SELECT crash_id, user_id, crash_time, session_start, session_end,
           provider, event_id, exception_code, faulting_module, message
    FROM crashes
    {w}
    ORDER BY crash_time DESC
    LIMIT %s;
    """
    params.append(limit)

    return jsonify(make_json_safe(fetch_all(sql, params)))


@app.get("/admin/crashes/summary")
@require_admin
def admin_crashes_summary():
    user = request.args.get("user", "").strip()
    limit = int(request.args.get("limit", "50"))

    where = ""
    params = []
    if user:
        where = "WHERE user_id=%s"
        params.append(user)

    sql = f"""
    SELECT
      CONCAT(COALESCE(exception_code,'no-code'),' | ',
             COALESCE(faulting_module,'no-module'),' | ',
             COALESCE(event_id::text,'0')) AS signature,
      COUNT(*)::int AS count,
      MAX(crash_time) AS last_seen,
      LEFT(MAX(message), 120) AS example
    FROM crashes
    {where}
    GROUP BY signature
    ORDER BY count DESC, last_seen DESC
    LIMIT %s;
    """
    params.append(limit)

    return jsonify(make_json_safe(fetch_all(sql, params)))


# ----------------------------
# Charts: Sessions
# ----------------------------
@app.get("/admin/charts/sessions_per_user")
@require_admin
def chart_sessions_per_user():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT user_id, COUNT(*)::int AS sessions
    FROM sessions
    WHERE session_start >= %s AND session_start <= %s
    GROUP BY user_id
    ORDER BY sessions DESC;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/session_duration_daily")
@require_admin
def chart_session_duration_daily():
    dt_from, dt_to = get_from_to()

    # Works if total_duration is INTERVAL
    sql = """
    SELECT
      to_char(date_trunc('day', session_start), 'YYYY-MM-DD') AS day,
      ROUND(SUM(EXTRACT(EPOCH FROM total_duration)) / 3600.0, 4) AS hours
    FROM sessions
    WHERE session_start >= %s AND session_start <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/activity_hourly")
@require_admin
def chart_activity_hourly():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      EXTRACT(HOUR FROM session_start)::int AS hour,
      COUNT(*)::int AS sessions
    FROM sessions
    WHERE session_start >= %s AND session_start <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/daily_users")
@require_admin
def chart_daily_users():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      to_char(date_trunc('day', session_start), 'YYYY-MM-DD') AS day,
      COUNT(DISTINCT user_id)::int AS active_users
    FROM sessions
    WHERE session_start >= %s AND session_start <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/weekly_users")
@require_admin
def chart_weekly_users():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      to_char(date_trunc('week', session_start), 'YYYY-MM-DD') AS week,
      COUNT(DISTINCT user_id)::int AS active_users
    FROM sessions
    WHERE session_start >= %s AND session_start <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/new_vs_returning")
@require_admin
def chart_new_vs_returning():
    dt_from, dt_to = get_from_to()
    sql = """
    WITH first_seen AS (
      SELECT user_id, MIN(session_start) AS first_time
      FROM sessions
      GROUP BY user_id
    ),
    active_in_range AS (
      SELECT DISTINCT user_id
      FROM sessions
      WHERE session_start >= %s AND session_start <= %s
    )
    SELECT
      SUM(CASE WHEN f.first_time >= %s AND f.first_time <= %s THEN 1 ELSE 0 END)::int AS new_users,
      SUM(CASE WHEN f.first_time < %s THEN 1 ELSE 0 END)::int AS returning_users
    FROM active_in_range a
    JOIN first_seen f USING(user_id);
    """
    row = fetch_one(sql, [dt_from, dt_to, dt_from, dt_to, dt_from])
    return jsonify(make_json_safe(row or {"new_users": 0, "returning_users": 0}))


# ----------------------------
# Charts: Crashes
# ----------------------------
@app.get("/admin/charts/crashes_daily")
@require_admin
def chart_crashes_daily():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      to_char(date_trunc('day', crash_time), 'YYYY-MM-DD') AS day,
      COUNT(*)::int AS crashes
    FROM crashes
    WHERE crash_time >= %s AND crash_time <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/crashes_hourly")
@require_admin
def chart_crashes_hourly():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      EXTRACT(HOUR FROM crash_time)::int AS hour,
      COUNT(*)::int AS crashes
    FROM crashes
    WHERE crash_time >= %s AND crash_time <= %s
    GROUP BY 1
    ORDER BY 1;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/crashes_by_module")
@require_admin
def chart_crashes_by_module():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT COALESCE(faulting_module,'unknown') AS module, COUNT(*)::int AS crashes
    FROM crashes
    WHERE crash_time >= %s AND crash_time <= %s
    GROUP BY 1
    ORDER BY crashes DESC
    LIMIT 12;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/crashes_by_exception")
@require_admin
def chart_crashes_by_exception():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT COALESCE(exception_code,'unknown') AS exception, COUNT(*)::int AS crashes
    FROM crashes
    WHERE crash_time >= %s AND crash_time <= %s
    GROUP BY 1
    ORDER BY crashes DESC
    LIMIT 12;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


@app.get("/admin/charts/crashes_top_signatures")
@require_admin
def chart_crashes_top_signatures():
    dt_from, dt_to = get_from_to()
    sql = """
    SELECT
      CONCAT(COALESCE(exception_code,'no-code'),' | ',
             COALESCE(faulting_module,'no-module'),' | ',
             COALESCE(event_id::text,'0')) AS signature,
      COUNT(*)::int AS crashes
    FROM crashes
    WHERE crash_time >= %s AND crash_time <= %s
    GROUP BY 1
    ORDER BY crashes DESC
    LIMIT 10;
    """
    return jsonify(make_json_safe(fetch_all(sql, [dt_from, dt_to])))


if __name__ == "__main__":
    host = os.getenv("ADMIN_HOST", "127.0.0.1")
    port = int(os.getenv("ADMIN_PORT", "5001"))
    app.run(host=host, port=port, debug=True)
