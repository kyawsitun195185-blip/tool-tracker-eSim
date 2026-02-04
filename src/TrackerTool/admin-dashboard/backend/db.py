import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5435")),
        dbname=os.getenv("DB_NAME", "esim_tracker"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )

def _json_safe(v):
    if isinstance(v, (datetime, date)):
        # "2026-01-28 10:41:11" style (space between date/time)
        return v.isoformat(sep=" ")
    if isinstance(v, timedelta):
        # You can return hours float OR "HH:MM:SS"
        # hours float:
        return round(v.total_seconds() / 3600, 6)
        # OR string:
        # return str(v)
    return v

def _row_to_dict(row):
    d = dict(row)
    return {k: _json_safe(v) for k, v in d.items()}

def fetch_all(sql: str, params=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

def fetch_one(sql: str, params=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or [])
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn.close()

def execute(sql: str, params=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()
