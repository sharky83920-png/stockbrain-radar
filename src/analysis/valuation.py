"""估值分析：本益比河流圖、TTM EPS、股利年化。"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import numpy as np
import pandas as pd

from ..data import finmind_client as fm


def ttm_eps_series(sid: str, days: int = 1300) -> pd.DataFrame:
    """回傳每季的 TTM EPS（近四季加總）。欄位: date(季底), ttm_eps。"""
    fs = fm.financial_statements(sid, days=days)
    if fs.empty:
        return pd.DataFrame(columns=["date", "ttm_eps"])
    eps = fs[fs["type"] == "EPS"].copy()
    if eps.empty:
        return pd.DataFrame(columns=["date", "ttm_eps"])
    eps["date"] = pd.to_datetime(eps["date"])
    eps = eps.sort_values("date")
    eps["ttm_eps"] = eps["value"].rolling(4).sum()
    return eps.dropna(subset=["ttm_eps"])[["date", "ttm_eps"]].reset_index(drop=True)


def pe_band(sid: str, years: int = 3, percentiles=(10, 30, 50, 70, 90)) -> dict[str, Any]:
    """本益比河流圖資料。

    回傳: {df, multiples, current_per}
      df: 欄位 date, close, ttm_eps, per, 以及每個本益比倍數的價格帶 'PER xx'
      multiples: 用到的本益比倍數(由歷史 PER 百分位數決定)
    """
    days = years * 365 + 60
    price = fm.stock_price(sid, days=days)
    if price.empty:
        return {"df": pd.DataFrame(), "multiples": [], "current_per": None}
    price = price[["date", "close"]].copy()
    price["date"] = pd.to_datetime(price["date"])
    price = price.sort_values("date")

    ttm = ttm_eps_series(sid, days=days + 400)
    if ttm.empty:
        return {"df": pd.DataFrame(), "multiples": [], "current_per": None}

    # 每個交易日對應到「當下最近一季」的 TTM EPS
    merged = pd.merge_asof(price, ttm, on="date", direction="backward")
    merged = merged.dropna(subset=["ttm_eps"])
    merged = merged[merged["ttm_eps"] > 0].copy()
    if merged.empty:
        return {"df": pd.DataFrame(), "multiples": [], "current_per": None}

    merged["per"] = merged["close"] / merged["ttm_eps"]
    mults = [round(float(np.percentile(merged["per"], p)), 1) for p in percentiles]
    mults = sorted(set(mults))
    for m in mults:
        merged[f"PER {m}"] = m * merged["ttm_eps"]

    current_per = round(float(merged["per"].iloc[-1]), 1)
    return {"df": merged, "multiples": mults, "current_per": current_per}


def dividend_analysis(sid: str, price: float | None) -> dict[str, Any]:
    """股利分析：近一年現金股利加總 + 依最近一次年化的預估，以及對應殖利率。"""
    df = fm.dividend(sid, days=1500)
    if df.empty:
        return {"error": "無股利資料"}
    df = df.copy()
    df["cash"] = df.get("CashEarningsDistribution", 0).fillna(0) + df.get("CashStatutorySurplus", 0).fillna(0)
    df = df[df["cash"] > 0]
    if df.empty:
        return {"note": "近年無現金股利"}

    today = _dt.date.today()

    def _d(s):
        try:
            return _dt.date.fromisoformat(str(s))
        except Exception:
            return None

    df["ex"] = df["CashExDividendTradingDate"].map(_d)
    df = df.dropna(subset=["ex"]).sort_values("ex")

    one_year_ago = today - _dt.timedelta(days=365)
    ttm_rows = df[(df["ex"] > one_year_ago) & (df["ex"] <= today)]
    ttm_sum = round(float(ttm_rows["cash"].sum()), 3)
    freq = len(ttm_rows)

    past = df[df["ex"] <= today]
    recent_cash = float(past["cash"].iloc[-1]) if not past.empty else float(df["cash"].iloc[-1])
    annualized = round(recent_cash * (freq if freq > 0 else 1), 3)

    out: dict[str, Any] = {
        "ttm_cash_dividend": ttm_sum,
        "ttm_payout_count": freq,
        "recent_cash_dividend": round(recent_cash, 3),
        "annualized_estimate": annualized,
        "recent_ex_date": str(past["ex"].iloc[-1]) if not past.empty else None,
    }
    if price:
        out["yield_ttm_pct"] = round(ttm_sum / price * 100, 2)
        out["yield_forward_pct"] = round(annualized / price * 100, 2)
    return out
