"""探針：驗證國泰投信 cwapi 的 ETF 持股 API 能從 Python 打通。

背景：FinMind 沒有 ETF 成分股資料集，所以 00878 的持股要改打國泰投信自家 API。
這支腳本只做「一次性驗證」——確認端點、TLS、回傳格式、以及「歷史日期可回補」，
確認後真正的 collector 寫在 src/data/etf_holdings.py。

用法：
    .venv\\Scripts\\python scripts\\probe_etf.py
"""
from __future__ import annotations

import json
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://cwapi.cathaysite.com.tw/api/ETF"
FUND = "CN"  # 00878 國泰永續高股息

# cwapi 會擋沒有瀏覽器來源標頭的請求（直接打會 403），補上 Origin/Referer/UA。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.cathaysite.com.tw",
    "Referer": "https://www.cathaysite.com.tw/",
}


def get(endpoint: str, **params) -> dict:
    params.setdefault("FundCode", FUND)
    params.setdefault("status", 1)
    r = requests.get(f"{BASE}/{endpoint}", params=params,
                     headers=HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()


def main() -> None:
    print("=== 今日持股 (GetETFDetailStockList, SearchDate=2026-07-23) ===")
    today = get("GetETFDetailStockList", SearchDate="2026-07-23")
    rows = today.get("result", [])
    print(f"檔數: {len(rows)}")
    for r in rows[:5]:
        print(f"  {r['stockCode'].strip():<6} {r['stockName']:<8} "
              f"股數={r['volumn']:>15}  權重={r['weights']}%")

    print("\n=== 歷史回補測試 (SearchDate=2024-01-15，換股前) ===")
    old = get("GetETFDetailStockList", SearchDate="2024-01-15")
    orows = old.get("result", [])
    print(f"檔數: {len(orows)}")
    for r in orows[:5]:
        print(f"  {r['stockCode'].strip():<6} {r['stockName']:<8} "
              f"股數={r['volumn']:>15}  權重={r['weights']}%")

    print("\n=== 非交易日測試 (SearchDate=2026-07-19，週日) ===")
    holiday = get("GetETFDetailStockList", SearchDate="2026-07-19")
    print(f"result 長度: {len(holiday.get('result') or [])}  (空=非交易日，回補時跳過)")

    print("\n=== 資產成分 (GetETFAssets) ===")
    assets = get("GetETFAssets", SearchDate="2026-07-23")
    print(json.dumps(assets.get("result"), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
