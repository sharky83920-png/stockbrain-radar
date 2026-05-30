"""簡單的 SQLite 快取：避免同一天重複打 FinMind。

payload 直接存 API 回傳的 records(JSON)。預設當天的快取有效，隔天自動失效。
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cache.sqlite"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS api_cache "
        "(key TEXT PRIMARY KEY, fetched_date TEXT, payload TEXT)"
    )
    return conn


def get(key: str, max_age_days: int = 1) -> list | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT fetched_date, payload FROM api_cache WHERE key=?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    fetched_date, payload = row
    age = (_dt.date.today() - _dt.date.fromisoformat(fetched_date)).days
    if age > max_age_days:
        return None
    return json.loads(payload)


def put(key: str, records: list) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, fetched_date, payload) VALUES (?,?,?)",
            (key, _dt.date.today().isoformat(), json.dumps(records)),
        )
        conn.commit()
    finally:
        conn.close()
