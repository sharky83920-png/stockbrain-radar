"""新聞來源整合：Google News RSS（主，免金鑰、量大）+ FinMind（補）。

回傳統一欄位：date / stock_id / source / title / link。
"""
from __future__ import annotations

import urllib.parse
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from . import finmind_client as fm

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_COLS = ["date", "stock_id", "source", "title", "link"]


def google_news(query: str, limit: int = 80) -> pd.DataFrame:
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-TW"
    r = requests.get(url, headers=_UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    rows = []
    for it in root.findall(".//item")[:limit]:
        title = it.findtext("title") or ""
        link = it.findtext("link") or ""
        pub = it.findtext("pubDate")
        src_el = it.find("{*}source")
        source = src_el.text if src_el is not None and src_el.text else "Google News"
        try:
            date = parsedate_to_datetime(pub).strftime("%Y-%m-%d %H:%M")
        except Exception:
            date = (pub or "")[:16]
        # Google News 標題常為「標題 - 來源」，去掉尾巴來源
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)]
        rows.append({"date": date, "stock_id": "", "source": source, "title": title, "link": link})
    return pd.DataFrame(rows, columns=_COLS)


def get_news(stock_id: str, name: str | None = None, days: int = 21) -> pd.DataFrame:
    """整合新聞：Google News（用『股名 代號』搜尋）+ FinMind，去重後依日期排序。"""
    frames = []
    query = f"{name} {stock_id}" if name else stock_id
    try:
        g = google_news(query)
        if not g.empty:
            frames.append(g)
    except Exception:
        pass
    try:
        fmn = fm.news(stock_id, days=days)
        if not fmn.empty:
            frames.append(fmn.reindex(columns=_COLS))
    except Exception:
        pass
    if not frames:
        return pd.DataFrame(columns=_COLS)
    df = pd.concat(frames, ignore_index=True)
    df["title"] = df["title"].astype(str).str.strip()
    df = df[df["title"] != ""]
    df = df.drop_duplicates(subset="title").sort_values("date", ascending=False).reset_index(drop=True)
    return df
