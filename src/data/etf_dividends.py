"""00878 配息紀錄 + 配息組成（淨收益 vs 收益平準金）。

來源：國泰 cwapi `Fund/GetHistoryAllotInfo`（成立至今全部配息，乾淨 JSON）。
提供每期：配息金額、當期/年化配息率、含息報酬，以及公會規範的「兩分法」配息組成：
  - income_pct    每單位配息中屬「可分配淨利益」的比率
  - principal_pct 每單位配息中屬「收益平準金」的比率（動用平準金≈配自己的本金）

⚠️ 限制：這個兩分法「淨收益」把 股利＋利息＋已實現資本利得 全部算在一起，
   **無法單獨拆出資本利得**。要回答「配息裡資本利得佔多少」需用 bottom-up 方式
   （成分股實收現金股利 vs 基金實配），見 Phase 2 規劃，不在本模組。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import requests
import urllib3

from . import cache
from .etf_holdings import _fund_code, _HEADERS, CathayETFError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_URL = ("https://cwapi.cathaysite.com.tw/api/Fund/GetHistoryAllotInfo"
        "?fundCode={fc}&IsFromBorn=true&StartYear=&EndYear="
        "&CurrentPage=1&PerPageCount=9999&status=1")


def fetch_dividends(fund: str = "00878", max_age_days: int = 1) -> pd.DataFrame:
    """成立至今每期配息 + 兩分法組成。回傳依配息年月新到舊排序的 DataFrame。

    欄位：allot_ym / pay_money / current_yield / year_yield / return_incl_allot /
          income_pct / principal_pct / base_date / ex_date / pay_date / period。
    """
    fc = _fund_code(fund)
    cache_key = f"cathay|GetHistoryAllotInfo|{fc}"
    rows = cache.get(cache_key, max_age_days=max_age_days)
    if rows is None:
        try:
            r = requests.get(_URL.format(fc=fc), headers=_HEADERS, timeout=30, verify=False)
            r.raise_for_status()
            rows = (r.json().get("result") or {}).get("fundAllotInfoList") or []
        except Exception as exc:
            stale = cache.get(cache_key, max_age_days=3650)
            if stale is not None:
                rows = stale
            else:
                raise CathayETFError(f"國泰配息 API 失敗：{exc}") from exc
        else:
            cache.put(cache_key, rows)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame({
        "allot_ym": [d["allotYearMonth"] for d in rows],
        "pay_money": [float(d["allotMoney"]) for d in rows],
        "current_yield": [float(d.get("currentAllot") or 0) for d in rows],
        "year_yield": [float(d.get("yearAllot") or 0) for d in rows],
        "return_incl_allot": [float(d.get("currentReturnIncludeAllot") or 0) for d in rows],
        "income_pct": [float(d.get("netIncomeDividedByAllot") or 0) for d in rows],
        "principal_pct": [float(d.get("principalDividedByAllot") or 0) for d in rows],
        "base_date": [d.get("baseDate") for d in rows],
        "ex_date": [d.get("transDate") for d in rows],
        "pay_date": [d.get("lendingDate") for d in rows],
        "period": [d.get("allotPeriod") for d in rows],
    })
    return df


def summary(fund: str = "00878") -> dict:
    """配息品質快覽：期數、動用平準金的期數、近一年配息合計。"""
    df = fetch_dividends(fund)
    if df.empty:
        return {}
    dipped = df[df["principal_pct"] > 0]
    return {
        "periods": len(df),
        "range": (df["allot_ym"].iloc[-1], df["allot_ym"].iloc[0]),
        "periods_using_principal": len(dipped),
        "principal_periods": dipped["allot_ym"].tolist(),
        "latest_year_yield": df["year_yield"].iloc[0],
    }
