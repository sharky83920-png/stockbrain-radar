"""題材地圖資料層：讀 theme_map.json → FinMind 批量抓漲跌幅 → 30min cache"""
from __future__ import annotations
import json
import pathlib
import streamlit as st
import pandas as pd

from src.data import finmind_client as fm

_MAP_PATH = pathlib.Path(r"G:\我的雲端硬碟\stockbrain\工具欄\theme_map.json")


def _load_map() -> dict:
    with open(_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def _all_sids(theme_map: dict) -> list[str]:
    seen, sids = set(), []
    for chain in theme_map.get("chains", []):
        for stage in chain.get("stages", []):
            for s in stage.get("stocks", []):
                sid = s["sid"]
                if sid not in seen:
                    seen.add(sid)
                    sids.append(sid)
    return sids


def _get_change(sid: str) -> float:
    """用 FinMind 抓近 5 個交易日收盤價，回傳最後一日漲跌幅%。失敗回 0.0。"""
    try:
        df = fm.stock_price(sid, days=7)
        if df.empty or "close" not in df.columns:
            return 0.0
        closes = df.sort_values("date")["close"].dropna()
        if len(closes) < 2:
            return 0.0
        return float((closes.iloc[-1] / closes.iloc[-2] - 1) * 100)
    except Exception:
        return 0.0


@st.cache_data(ttl=1800, show_spinner=False)
def get_theme_changes() -> tuple[dict, dict[str, float]]:
    """回傳 (theme_map dict, {sid: change_pct})。cache 30 分鐘。"""
    theme_map = _load_map()
    sids = _all_sids(theme_map)
    changes = {sid: _get_change(sid) for sid in sids}
    return theme_map, changes
