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


def pbr_band(sid: str, years: int = 3, percentiles=(20, 50, 80)) -> dict[str, Any]:
    """股價淨值比 PBR 評價帶（葛拉漢式，孫慶龍財務比率法第 4 種）。

    FinMind TaiwanStockPER 有每日 PBR，直接取近 N 年百分位當便宜/合理/昂貴倍數；
    每股淨值由「最新收盤 ÷ 最新 PBR」反推（與 PBR 序列同一口徑，不會對不上）。
    回傳: {df, multiples, current_pbr, bvps, conservative, neutral, optimistic, source}
    """
    days = years * 365 + 30
    raw = fm.per_pbr(sid, days=days)
    if raw.empty or "PBR" not in raw.columns:
        return {}
    df = raw[["date", "PBR"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["PBR"] = pd.to_numeric(df["PBR"], errors="coerce")
    df = df.dropna(subset=["PBR"])
    df = df[df["PBR"] > 0].sort_values("date")
    if len(df) < 60:
        return {}

    current_pbr = float(df["PBR"].iloc[-1])
    price = fm.stock_price(sid, days=15)
    if price.empty:
        return {}
    close = float(pd.to_numeric(price["close"], errors="coerce").dropna().iloc[-1])
    bvps = close / current_pbr

    lo, mid, hi = (round(float(np.percentile(df["PBR"], p)), 2) for p in percentiles)
    return {
        "df": df,
        "multiples": [lo, mid, hi],
        "current_pbr": round(current_pbr, 2),
        "bvps": round(bvps, 2),
        "conservative": round(lo * bvps, 2),
        "neutral": round(mid * bvps, 2),
        "optimistic": round(hi * bvps, 2),
        "source": f"近{years}年每日 PBR 百分位({percentiles[0]}/{percentiles[1]}/{percentiles[2]}) × 每股淨值 {bvps:,.1f} 元（最新收盤÷最新PBR反推）",
    }


def psr_band(sid: str, shares: float | None, years: int = 3,
             percentiles=(20, 50, 80), rolling_days: int = 60) -> dict[str, Any]:
    """股價營收比 PSR 評價帶（孫慶龍財務比率法第 5 種；投資家日報 2026-07-07 起
    對轉型期企業改用的主要評價法）。

    口徑對齊日報：每股營收 = 近 12 個月營收總合 ÷ 發行股數；
    「滾動式股價營收比」= 近 rolling_days 個交易日 PSR 平均 → × 每股營收 = 合理價。
    另以近 N 年每日 PSR 百分位給便宜/合理/昂貴帶（與本益比河流圖同骨架）。
    月營收於次月 10 日左右公布，歷史序列以「月份結束後 40 天」視為可得（保守避免前視）。
    股數採當前值回溯（台股股本變動小，帶 basis 說明）。shares 單位：股。
    """
    if not shares or shares <= 0:
        return {}
    rev = fm.month_revenue(sid, days=years * 365 + 460)
    if rev.empty:
        return {}
    rev = rev.copy()
    rev["revenue"] = pd.to_numeric(rev["revenue"], errors="coerce")
    rev = rev.dropna(subset=["revenue"])
    rev["ym"] = pd.to_datetime(rev["revenue_year"].astype(int).astype(str) + "-"
                               + rev["revenue_month"].astype(int).astype(str).str.zfill(2) + "-01")
    rev = rev.sort_values("ym").drop_duplicates("ym", keep="last")
    rev["rev_12m"] = rev["revenue"].rolling(12).sum()
    rev = rev.dropna(subset=["rev_12m"])
    if rev.empty:
        return {}
    # 該月營收約在次月 10 日公布 → 月初 +40 天當可得日
    rev["avail"] = rev["ym"] + pd.Timedelta(days=40)

    price = fm.stock_price(sid, days=years * 365 + 60)
    if price.empty:
        return {}
    px = price[["date", "close"]].copy()
    px["date"] = pd.to_datetime(px["date"])
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna().sort_values("date")

    merged = pd.merge_asof(px, rev[["avail", "rev_12m"]].rename(columns={"avail": "date"}),
                           on="date", direction="backward").dropna(subset=["rev_12m"])
    if len(merged) < 60:
        return {}
    merged["rev_ps"] = merged["rev_12m"] / shares
    merged["psr"] = merged["close"] / merged["rev_ps"]

    rev_ps_now = float(merged["rev_ps"].iloc[-1])
    current_psr = float(merged["psr"].iloc[-1])
    psr_roll = float(merged["psr"].tail(rolling_days).mean())

    lo, mid, hi = (round(float(np.percentile(merged["psr"], p)), 2) for p in percentiles)
    return {
        "df": merged,
        "multiples": [lo, mid, hi],
        "current_psr": round(current_psr, 2),
        "psr_rolling": round(psr_roll, 2),
        "rolling_days": rolling_days,
        "rev_ps": round(rev_ps_now, 2),
        "rev_12m": float(merged["rev_12m"].iloc[-1]),
        "fair_price_rolling": round(psr_roll * rev_ps_now, 2),   # 日報口徑合理價
        "conservative": round(lo * rev_ps_now, 2),
        "neutral": round(mid * rev_ps_now, 2),
        "optimistic": round(hi * rev_ps_now, 2),
        "source": f"近{years}年每日 PSR 百分位({percentiles[0]}/{percentiles[1]}/{percentiles[2]}) × 每股營收 {rev_ps_now:,.1f} 元"
                  f"（近12月營收 {merged['rev_12m'].iloc[-1]/1e8:,.0f} 億 ÷ 股數，股數採當前值回溯）",
    }
