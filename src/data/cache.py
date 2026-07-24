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


def _parse_fetched(value: str) -> _dt.datetime:
    """相容舊格式：舊資料只存日期（視為當天 00:00），新資料存完整時間戳。"""
    try:
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return _dt.datetime.combine(_dt.date.fromisoformat(value[:10]), _dt.time())


def get(key: str, max_age_days: int = 1) -> list | None:
    entry = get_entry(key)
    if entry is None:
        return None
    records, fetched_at = entry
    age = (_dt.date.today() - fetched_at.date()).days
    if age > max_age_days:
        return None
    return records


def get_entry(key: str) -> tuple[list, _dt.datetime] | None:
    """不檢查有效期，回傳 (records, 抓取時間)。給呼叫端自行判斷新舊或當備援。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT fetched_date, payload FROM api_cache WHERE key=?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    fetched, payload = row
    return json.loads(payload), _parse_fetched(fetched)


def put(key: str, records: list) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, fetched_date, payload) VALUES (?,?,?)",
            (key, _dt.datetime.now().isoformat(timespec="seconds"), json.dumps(records)),
        )
        conn.commit()
    finally:
        conn.close()
