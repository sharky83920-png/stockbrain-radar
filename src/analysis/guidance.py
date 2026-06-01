"""法說會 guidance 擷取（從新聞標題，best-effort；Gemini 版可後續升級）。

抓三個公司財測常見數字：全年營收成長率、毛利率、資本支出(億美元)。
只處理含「法說/法人說明會」的新聞。數字會做合理範圍 sanity check。
"""
from __future__ import annotations

import re

import pandas as pd

_REV = [
    re.compile(r"(?:全年|年度|營收|美元營收|年)\D{0,8}(?:成長|年增|看增|增長|暴增|增)\D{0,3}(\d{1,3})\s*%"),
    re.compile(r"(?:成長|年增|看增|暴增)\D{0,2}(\d)\s*成"),  # 近5成 -> 50
]
_GM = [
    re.compile(r"毛利率\D{0,6}(\d{2})(?:\.\d)?\s*%"),
    re.compile(r"毛利率\D{0,4}(?:挑戰|上看|破|逾|衝|飆破)\D{0,2}(\d)\s*成"),  # 挑戰6成 -> 60
]
_CAP = re.compile(r"資本支出.{0,12}?(?:\d{3,4}\s*[-~至]\s*)?(\d{3,4})\s*億美元")  # 取區間高標


def is_law_news(title: str) -> bool:
    return ("法說" in title) or ("法人說明會" in title)


def _first(pats, title: str) -> int | None:
    for i, p in enumerate(pats):
        m = p.search(title)
        if m:
            v = int(m.group(1))
            return v * 10 if i == 1 else v  # 第二式是「X成」
    return None


def extract_from_news(news_df: pd.DataFrame) -> list[dict]:
    rows = []
    if news_df is None or news_df.empty:
        return rows
    for _, r in news_df.iterrows():
        t = str(r["title"])
        if not is_law_news(t):
            continue
        rev, gm = _first(_REV, t), _first(_GM, t)
        cm = _CAP.search(t)
        cap = int(cm.group(1)) if cm else None
        # sanity check
        rev = rev if (rev and 0 < rev <= 200) else None
        gm = gm if (gm and 30 <= gm <= 80) else None
        cap = cap if (cap and 100 <= cap <= 3000) else None
        if rev or gm or cap:
            rows.append({
                "date": str(r["date"])[:10],
                "營收成長%": rev, "毛利率%": gm, "資本支出(億美元)": cap,
                "title": t, "link": r.get("link", ""),
            })
    return rows


def summarize(news_df: pd.DataFrame) -> dict:
    """彙整：每個指標取「被最多新聞講到的值」。回傳含 evidence 清單。"""
    rows = extract_from_news(news_df)
    if not rows:
        return {}

    def mode(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return max(set(vals), key=vals.count) if vals else None

    return {
        "營收成長%": mode("營收成長%"),
        "毛利率%": mode("毛利率%"),
        "資本支出(億美元)": mode("資本支出(億美元)"),
        "evidence": rows,
    }
