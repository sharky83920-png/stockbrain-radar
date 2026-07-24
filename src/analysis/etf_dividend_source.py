"""00878 配息「來源」拆解 —— bottom-up 驗證：配息到底是股利還是資本利得？

背景：官方配息組成只揭露「淨收益 vs 收益平準金」兩分法（00878 至今一直是 100%/0%），
無法拆出「股利 vs 資本利得」。本模組改用 Phase 1 的持股歷史，直接由下而上算：

  基金每年「實收現金股利/單位」 = Σ_成分股 (除息日持股 × 每股現金股利) ÷ 流通單位數
  對照 基金每年「實配金額/單位」（etf_dividends）

判讀（因平準金≈0）：
  實配/單位 ≈ 實收股利/單位  → 配息是真・股利穿透
  實配/單位 >  實收股利/單位  → 超出部分來自「已實現資本利得」增配
  實配/單位 <  實收股利/單位  → 基金保留部分股利（未全數配出）

限制：持股歷史始於 2023-01，故只分析 2023 年起；每股現金股利用 FinMind。
     這是估算（除息日持股用最近一筆快照近似），非基金帳務數字。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd

from ..data import finmind_client as fm
from ..data import etf_holdings as eh
from ..data import etf_dividends as ed


def _nearest_holdings_shares(fund: str, code: str, on_date: str) -> int:
    """某成分股在 on_date（除息日）當下、基金持有的股數，取 ≤ on_date 最近一筆快照。"""
    dates = [d for d in eh.stored_dates(fund) if d <= on_date]
    if not dates:
        return 0
    snap = eh.load_store(fund)["snapshots"][dates[-1]]
    for r in snap:
        if r["code"] == code:
            return int(r["shares"])
    return 0


def _units_on(fund: str, on_date: str) -> float | None:
    """流通單位數，取 on_date 當日；非交易日往前找幾天。"""
    d = _dt.date.fromisoformat(on_date)
    for _ in range(7):
        a = eh.fetch_assets(fund, d.isoformat())
        if a.get("outstanding_units"):
            return a["outstanding_units"]
        d -= _dt.timedelta(days=1)
    return None


def dividends_received(fund: str = "00878", start_year: int = 2023) -> pd.DataFrame:
    """逐筆：每檔成分股每次除息，基金當時持股 × 每股現金股利 = 實收股利，換算每單位。"""
    store = eh.load_store(fund)
    codes = sorted({r["code"] for rows in store["snapshots"].values() for r in rows})
    recs = []
    for code in codes:
        try:
            div = fm.dividend(code, days=1600)
        except Exception:
            continue
        if div.empty or "CashExDividendTradingDate" not in div.columns:
            continue
        for r in div.itertuples(index=False):
            ex = str(getattr(r, "CashExDividendTradingDate", "") or "")
            cash = float(getattr(r, "CashEarningsDistribution", 0) or 0)
            if len(ex) < 10 or cash <= 0 or int(ex[:4]) < start_year:
                continue
            shares = _nearest_holdings_shares(fund, code, ex)
            if shares <= 0:
                continue
            units = _units_on(fund, ex)
            if not units:
                continue
            twd = shares * cash
            recs.append({
                "year": int(ex[:4]), "ex_date": ex, "code": code,
                "name": fm.stock_name(code) or code,
                "shares": shares, "cash_per_share": cash,
                "twd_received": twd, "units": units,
                "per_unit": twd / units,
            })
    return pd.DataFrame(recs).sort_values(["year", "ex_date"], ignore_index=True)


def annual_source(fund: str = "00878", start_year: int = 2023) -> pd.DataFrame:
    """每年：實收股利/單位 vs 實配/單位，推估資本利得貢獻。"""
    recv = dividends_received(fund, start_year)
    by_year_recv = recv.groupby("year")["per_unit"].sum() if not recv.empty else pd.Series(dtype=float)

    div = ed.fetch_dividends(fund)
    div["year"] = div["ex_date"].str[:4].astype(int)  # 依除息日曆年歸戶
    paid = div[div["year"] >= start_year].groupby("year")["pay_money"].sum()

    years = sorted(set(by_year_recv.index) | set(paid.index))
    rows = []
    for y in years:
        rec = float(by_year_recv.get(y, 0.0))
        pay = float(paid.get(y, 0.0))
        rows.append({
            "year": y,
            "received_div_per_unit": round(rec, 4),   # 實收現金股利/單位
            "paid_per_unit": round(pay, 4),            # 實配/單位
            "gap_capital_gain_est": round(pay - rec, 4),  # 推估來自資本利得(+)/保留股利(-)
            "div_cover_ratio": round(rec / pay, 3) if pay else None,  # 股利覆蓋率
        })
    return pd.DataFrame(rows)
