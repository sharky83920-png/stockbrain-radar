"""免金鑰的新聞重點整理：把標題依主題分類、統計、列代表標題。

不需要 LLM，當 Gemini 未設定時的摘要替代方案。
"""
from __future__ import annotations

import pandas as pd

THEMES: list[tuple[str, list[str]]] = [
    ("法人/籌碼動向", ["外資", "投信", "法人", "買超", "賣超", "目標價", "評等", "調升", "調降", "上看", "升評", "降評"]),
    ("營運/財報", ["營收", "財報", "EPS", "獲利", "毛利", "法說", "季", "業績", "訂單"]),
    ("產業/技術趨勢", ["AI", "奈米", "製程", "供應鏈", "產能", "報價", "晶片", "CoWoS", "先進封裝", "資料中心"]),
    ("股利/配息", ["股利", "配息", "除息", "殖利率", "現金股利"]),
    ("股價/盤勢", ["股價", "創高", "天價", "漲", "跌", "K線", "技術", "鉅額"]),
]


def digest(news_df: pd.DataFrame, top_per_theme: int = 3) -> str:
    """回傳 markdown 重點整理。"""
    if news_df is None or news_df.empty:
        return "近期無新聞可整理。"
    titles = news_df["title"].astype(str).tolist()
    lines = [f"**自動重點整理**（共 {len(titles)} 則，依主題分類；未接 AI）\n"]
    used = set()
    for theme, kws in THEMES:
        matched = [t for t in titles if any(k in t for k in kws)]
        if not matched:
            continue
        lines.append(f"**{theme}**（{len(matched)} 則）")
        for t in matched[:top_per_theme]:
            if t in used:
                continue
            used.add(t)
            lines.append(f"- {t[:60]}")
        lines.append("")
    if len(lines) <= 1:
        return "新聞無法歸類到主要主題，請直接看下方列表。"
    return "\n".join(lines)
