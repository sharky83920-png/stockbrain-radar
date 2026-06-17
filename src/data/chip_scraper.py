"""籌碼爬蟲（買賣家數差 / 主力買賣超）—— 免費網站來源，脆弱，需定期維護。

⚠️ 注意：
- 這層資料 FinMind 免費版沒有，改爬免費網站（HiStock / Goodinfo / WantGoo）。
- 網站改版就可能壞掉，屬「best-effort」。**僅供個人研究，請勿大量抓取或轉發散布**。
- 有些網站是 JavaScript 動態載入，純 requests 抓不到 → 要找有「伺服器直接吐 HTML」的來源。
"""
from __future__ import annotations

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def get(url: str, timeout: int = 20) -> requests.Response:
    """帶瀏覽器標頭的 GET。"""
    return requests.get(url, headers=_HEADERS, timeout=timeout)
