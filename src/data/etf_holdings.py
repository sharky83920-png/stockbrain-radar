"""00878（及其他國泰 ETF）成分股資料地基。

FinMind 沒有 ETF 成分股資料集，所以持股改打國泰投信自家 API（cwapi.cathaysite.com.tw）。
已驗證：可帶 SearchDate 查任意歷史日期 → 能一次回補整段持股歷史（見 scripts/probe_etf.py）。

本模組分三段：
  (A) API client   ── 打 cwapi 取某日成分股 / 資產淨值，透過 cache.py 快取。
  (B) 快照倉庫     ── 把每日持股存進 Obsidian vault 的 JSON，跨機由 Google Drive 同步。
  (C) 回補 / diff  ── 批次回補歷史 + 計算股數變化（加碼/減碼/新增/剔除）。

價格 / 推估成本不在這層（那是 Phase 2，改用 TWSE OpenAPI）。這層只負責「878 持有什麼、何時變動」。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

import pandas as pd
import requests
import urllib3

from . import cache

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 基金代碼對照 -------------------------------------------------------
# 國泰 cwapi 用自家 FundCode，不是掛牌代號。需要別檔再擴充這張表。
FUND_CODES: dict[str, str] = {
    "00878": "CN",  # 國泰台灣ESG永續高股息
}


def _fund_code(fund: str) -> str:
    """接受掛牌代號（00878）或 cwapi FundCode（CN），統一轉成 cwapi FundCode。"""
    fund = str(fund).strip()
    if fund in FUND_CODES:
        return FUND_CODES[fund]
    if fund in FUND_CODES.values():
        return fund
    raise ValueError(f"未知的基金代碼 {fund!r}，請先在 FUND_CODES 補上對照。")


# =====================================================================
# (A) API client
# =====================================================================
_BASE = "https://cwapi.cathaysite.com.tw/api"
# cwapi 會擋沒有瀏覽器來源標頭的請求（純 requests 直打會 403）。
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.cathaysite.com.tw",
    "Referer": "https://www.cathaysite.com.tw/",
}


class CathayETFError(RuntimeError):
    pass


def _get(endpoint: str, fund_code: str, search_date: str | None = None,
         timeout: int = 30) -> list | dict | None:
    """打 cwapi 一個端點，透過 cache 快取後回傳 result。

    歷史日期的持股是定案資料、永不變動 → 幾乎永久快取；今日資料當天有效。
    """
    params = {"FundCode": fund_code, "status": 1}
    if search_date:
        params["SearchDate"] = search_date
    cache_key = f"cathay|{endpoint}|{fund_code}|{search_date}"

    # 過去日期：快取視為永久有效；今天/未給日期：當天有效。
    today = _dt.date.today().isoformat()
    is_past = bool(search_date) and search_date < today
    max_age = 3650 if is_past else 1
    cached = cache.get(cache_key, max_age_days=max_age)
    if cached is not None:
        return cached

    url = f"{_BASE}/{endpoint}"
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=timeout, verify=False)
        r.raise_for_status()
        result = r.json().get("result")
    except Exception as exc:  # 斷線 / 403 時退回舊快取，完全沒快取才報錯
        stale = cache.get(cache_key, max_age_days=3650)
        if stale is not None:
            return stale
        raise CathayETFError(f"國泰 ETF API 失敗（{endpoint} {search_date}）：{exc}") from exc

    # result 可能是 list（成分股）或 dict（資產淨值）。存進快取（含空 list，代表非交易日）。
    cache.put(cache_key, result if result is not None else [])
    return result


def _to_int(s: str) -> int:
    return int(str(s).replace(",", "").strip() or 0)


def fetch_holdings(fund: str = "00878", search_date: str | None = None) -> pd.DataFrame:
    """取某日成分股。回傳欄位：date / stock_code / stock_name / shares / weight。

    search_date 給 None 代表最近一個交易日（cwapi 會自動回最新）。
    非交易日回空 DataFrame（欄位齊備）。
    """
    fc = _fund_code(fund)
    rows = _get("ETF/GetETFDetailStockList", fc, search_date) or []
    cols = ["date", "stock_code", "stock_name", "shares", "weight"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame({
        "date": search_date,
        "stock_code": [str(r["stockCode"]).strip() for r in rows],
        "stock_name": [str(r["stockName"]).strip() for r in rows],
        "shares": [_to_int(r["volumn"]) for r in rows],
        "weight": [float(r.get("weights") or 0) for r in rows],
    })
    return df[cols]


def fetch_assets(fund: str = "00878", search_date: str | None = None) -> dict:
    """取基金規模 / 淨值 / 流通單位數。回傳 dict（可能為空）。"""
    fc = _fund_code(fund)
    res = _get("ETF/GetETFAssets", fc, search_date)
    if not res:
        return {}
    d = res[0] if isinstance(res, list) else res
    def _num(k: str) -> float | None:
        v = d.get(k)
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    return {
        "date": d.get("preDate"),
        "fund_nav_total": _num("fundNav"),           # 基金資產總淨值
        "nav_per_unit": _num("fundPerNav"),          # 每單位淨值
        "outstanding_units": _num("fundOutstandingShares"),  # 流通單位數
    }


# =====================================================================
# (B) 快照倉庫（vault JSON，跨機由 Google Drive 同步）
# =====================================================================
# 目錄可用環境變數 RADAR_ETF_DIR 覆寫（換 Mac 時設定）。
_DEFAULT_DIR = r"G:\我的雲端硬碟\stockbrain\工具欄"


def _store_path(fund: str) -> Path:
    base = Path(os.environ.get("RADAR_ETF_DIR", _DEFAULT_DIR))
    return base / f"etf_holdings_{fund}.json"


def load_store(fund: str = "00878") -> dict:
    """讀整個倉庫：{fund, updated_at, snapshots:{date:[{code,name,shares,weight}]}}。"""
    p = _store_path(fund)
    if not p.exists():
        return {"fund": fund, "updated_at": None, "snapshots": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"fund": fund, "updated_at": None, "snapshots": {}}


def _save_store(fund: str, store: dict) -> None:
    p = _store_path(fund)
    p.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def save_snapshot(fund: str, date: str, df: pd.DataFrame) -> None:
    """把某日成分股寫進倉庫（同日覆寫）。空 df（非交易日）不寫。"""
    if df.empty:
        return
    store = load_store(fund)
    store["snapshots"][date] = [
        {"code": r.stock_code, "name": r.stock_name,
         "shares": int(r.shares), "weight": float(r.weight)}
        for r in df.itertuples(index=False)
    ]
    _save_store(fund, store)


def stored_dates(fund: str = "00878") -> list[str]:
    return sorted(load_store(fund)["snapshots"].keys())


def holdings_on(fund: str, date: str) -> pd.DataFrame:
    """從倉庫取某日持股（DataFrame）；倉庫沒有就即時抓一次。"""
    snap = load_store(fund)["snapshots"].get(date)
    if snap is None:
        return fetch_holdings(fund, date)
    return pd.DataFrame([
        {"date": date, "stock_code": r["code"], "stock_name": r["name"],
         "shares": r["shares"], "weight": r["weight"]}
        for r in snap
    ])


def latest(fund: str = "00878") -> tuple[str | None, pd.DataFrame]:
    """倉庫中最新一日的 (date, 持股 DataFrame)。倉庫空則回 (None, 空)。"""
    dates = stored_dates(fund)
    if not dates:
        return None, pd.DataFrame()
    return dates[-1], holdings_on(fund, dates[-1])


# =====================================================================
# (C) 回補 + 股數變化 diff
# =====================================================================
def _trading_days(start: str, end: str) -> list[str]:
    """start~end（含端點）所有平日（週一~五）。國定假日靠 API 回空自動略過。"""
    d0 = _dt.date.fromisoformat(start)
    d1 = _dt.date.fromisoformat(end)
    out = []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _dt.timedelta(days=1)
    return out


def backfill(fund: str = "00878", start: str = "2023-01-01",
             end: str | None = None, skip_stored: bool = True,
             log=print) -> int:
    """回補 start~end 之間每個交易日的持股到倉庫。回傳新寫入的天數。

    skip_stored=True 時跳過倉庫已有的日期（可重跑續補，不重打 API）。
    非交易日 API 回空、自動略過。歷史資料有永久快取，重跑很快。
    """
    end = end or _dt.date.today().isoformat()
    have = set(stored_dates(fund)) if skip_stored else set()
    days = [d for d in _trading_days(start, end) if d not in have]
    written = 0
    for i, d in enumerate(days):
        try:
            df = fetch_holdings(fund, d)
        except CathayETFError as exc:
            log(f"  {d} 失敗：{exc}")
            continue
        if df.empty:
            continue
        save_snapshot(fund, d, df)
        written += 1
        if written % 25 == 0:
            log(f"  已寫入 {written} 天（進度 {i + 1}/{len(days)}，最新 {d}）")
    log(f"回補完成：新增 {written} 天，倉庫現有 {len(stored_dates(fund))} 天。")
    return written


def constituent_events(fund: str = "00878") -> pd.DataFrame:
    """成分股「新增/剔除」時間軸（換股事件）。掃全部快照、相鄰日比對代碼集合。

    回傳欄位：date / added（新增名單） / removed（剔除名單）。只列有異動的日子。
    這是真正的換股訊號（相對於每日創造/贖回造成的等比漂移）。
    """
    store = load_store(fund)["snapshots"]
    dates = sorted(store)
    name = {}
    for d in dates:
        for r in store[d]:
            name[r["code"]] = r["name"]
    rows = []
    for prev, cur in zip(dates, dates[1:]):
        pset = {r["code"] for r in store[prev]}
        cset = {r["code"] for r in store[cur]}
        added = [name.get(c, c) for c in sorted(cset - pset)]
        removed = [name.get(c, c) for c in sorted(pset - cset)]
        if added or removed:
            rows.append({"date": cur, "added": added, "removed": removed})
    return pd.DataFrame(rows)


def share_changes(fund: str, date: str, prev_date: str | None = None) -> pd.DataFrame:
    """比較 date 與前一個有紀錄日的股數，標出加碼/減碼/新增/剔除。

    回傳欄位：stock_code / stock_name / shares / prev_shares / delta / pct / event。
    event ∈ {新增, 剔除, 加碼, 減碼, 不變}。prev_date 未給時自動取倉庫中前一日。
    """
    dates = stored_dates(fund)
    if prev_date is None:
        idx = dates.index(date) if date in dates else len(dates)
        prev_date = dates[idx - 1] if idx > 0 else None

    cur = holdings_on(fund, date).set_index("stock_code")
    prev = (holdings_on(fund, prev_date).set_index("stock_code")
            if prev_date else pd.DataFrame(columns=["stock_name", "shares"]))

    codes = sorted(set(cur.index) | set(prev.index))
    recs = []
    for c in codes:
        s = int(cur.loc[c, "shares"]) if c in cur.index else 0
        ps = int(prev.loc[c, "shares"]) if c in prev.index else 0
        name = (cur.loc[c, "stock_name"] if c in cur.index
                else prev.loc[c, "stock_name"])
        delta = s - ps
        if ps == 0 and s > 0:
            event = "新增"
        elif s == 0 and ps > 0:
            event = "剔除"
        elif delta > 0:
            event = "加碼"
        elif delta < 0:
            event = "減碼"
        else:
            event = "不變"
        recs.append({
            "stock_code": c, "stock_name": name, "shares": s, "prev_shares": ps,
            "delta": delta, "pct": (delta / ps * 100 if ps else None), "event": event,
        })
    df = pd.DataFrame(recs)
    return df.sort_values("delta", key=lambda s: s.abs(), ascending=False, ignore_index=True)
