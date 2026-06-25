"""個股專屬事件（法說會 / 財報日 / 股東會 / 除權息…）。

存成 vault JSON，跨機由 Google Drive 同步、Obsidian 可直接編。路徑可用環境變數
RADAR_STOCK_EVENTS_PATH 覆寫，預設 G:\\我的雲端硬碟\\stockbrain\\工具欄\\個股事件.json。

為何手動維護而非爬 MOPS：清單僅數檔、法說會/財報季頻一次，手動最穩、不會因 MOPS
改版而壞。台積電這類大型股的年度法說會表早已公布，可一次填好。

JSON 格式（以股票代號為 key）：
{
  "2330": [
    {"date": "2026-07-16", "type": "法說會", "note": "Q2 法說會（財報+展望）"}
  ]
}
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

_DEFAULT_PATH = r"G:\我的雲端硬碟\stockbrain\工具欄\個股事件.json"

# 事件類型 → 預設提示（note 留空時用）
_HINTS = {
    "法說會": "公司法說會，財報數字與展望同步出爐",
    "財報": "季財報公布",
    "股東會": "股東會（股利/董事改選等議案）",
    "除息": "除息交易日",
    "除權": "除權交易日",
}


def _path() -> Path:
    return Path(os.environ.get("RADAR_STOCK_EVENTS_PATH", _DEFAULT_PATH))


def _load_raw() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def upcoming(sid: str, today: date | None = None) -> list[dict]:
    """回某股未來事件（含今天），依日期排序。

    每筆與 macro_data.upcoming_events() 同形：{date, days, name, market, hint}，
    market 固定為「本檔」，方便橫幅合併排序。
    """
    today = today or date.today()
    out: list[dict] = []
    for e in _load_raw().get(str(sid), []):
        d = e.get("date")
        if not d or d < today.isoformat():
            continue
        try:
            days = (date.fromisoformat(d) - today).days
        except Exception:
            continue
        typ = e.get("type", "事件")
        out.append({
            "date": d,
            "days": days,
            "name": typ,
            "market": "本檔",
            "hint": e.get("note") or _HINTS.get(typ, ""),
        })
    out.sort(key=lambda x: x["date"])
    return out
