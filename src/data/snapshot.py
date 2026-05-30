"""個股研究快照：把 FinMind 各資料集聚合成 SOP 要看的指標。

回傳一個巢狀 dict，分四區：價格 / 籌碼 / 基本面 / 估值。
每一區的計算都包在 try/except，單區失敗不影響其他區。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from . import finmind_client as fm

TRADING_DAYS_WINDOW = 20  # 「近 20 日」法人/籌碼觀察窗


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# --- 各區計算 ---------------------------------------------------------------

def _price_section(sid: str) -> dict[str, Any]:
    df = fm.stock_price(sid, days=30).sort_values("date")
    if df.empty:
        return {"error": "無股價資料"}
    last = df.iloc[-1]
    prev_close = last["close"] - last["spread"]
    pct = (last["spread"] / prev_close * 100) if prev_close else 0.0
    return {
        "date": last["date"],
        "close": float(last["close"]),
        "change": float(last["spread"]),
        "change_pct": round(pct, 2),
        "volume_lots": int(last["Trading_Volume"] // 1000),
    }


def _chips_section(sid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 三大法人近 N 交易日淨買賣（張）
    inst = fm.institutional_investors(sid, days=45)
    if not inst.empty:
        inst = inst.copy()
        inst["net"] = (inst["buy"] - inst["sell"]) / 1000.0  # 股 -> 張
        recent_dates = sorted(inst["date"].unique())[-TRADING_DAYS_WINDOW:]
        recent = inst[inst["date"].isin(recent_dates)]

        def net_of(name: str) -> float:
            return round(float(recent.loc[recent["name"] == name, "net"].sum()), 1)

        out["foreign_net_20d_lots"] = net_of("Foreign_Investor")
        out["trust_net_20d_lots"] = net_of("Investment_Trust")
        out["window_days"] = len(recent_dates)

    # 融資 / 融券餘額 + 趨勢（張）
    ms = fm.margin_short(sid, days=45).sort_values("date")
    if not ms.empty:
        latest = ms.iloc[-1]
        first = ms.iloc[0]
        out["margin_balance_lots"] = int(latest["MarginPurchaseTodayBalance"])
        out["margin_change_lots"] = int(
            latest["MarginPurchaseTodayBalance"] - first["MarginPurchaseTodayBalance"]
        )
        out["short_balance_lots"] = int(latest["ShortSaleTodayBalance"])

    # 外資持股比例
    sh = fm.shareholding(sid, days=30).sort_values("date")
    if not sh.empty:
        out["foreign_holding_pct"] = float(sh.iloc[-1]["ForeignInvestmentSharesRatio"])

    return out


def _quarterly_series(fs: pd.DataFrame, type_name: str) -> list[tuple[str, float]]:
    sub = fs[fs["type"] == type_name].sort_values("date")
    return [(r["date"], float(r["value"])) for _, r in sub.iterrows()]


def _fundamentals_section(sid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 月營收 YoY
    rev = fm.month_revenue(sid, days=620)
    if not rev.empty:
        rev = rev.copy()
        by_ym = {(int(r["revenue_year"]), int(r["revenue_month"])): float(r["revenue"]) for _, r in rev.iterrows()}
        months = sorted(by_ym.keys())
        yoy_list = []
        for (y, m) in months[-3:]:
            prev = by_ym.get((y - 1, m))
            if prev:
                yoy_list.append({"month": f"{y}-{m:02d}", "yoy_pct": round((by_ym[(y, m)] - prev) / prev * 100, 1)})
        out["revenue_yoy_recent"] = yoy_list

    # 財報：EPS / 毛利率 / 營益率
    fs = fm.financial_statements(sid, days=500)
    if not fs.empty:
        eps = _quarterly_series(fs, "EPS")
        if eps:
            out["eps_recent"] = [{"q": d, "eps": v} for d, v in eps[-4:]]
            out["eps_ttm"] = round(sum(v for _, v in eps[-4:]), 2)
            # EPS YoY（同季去年比）
            if len(eps) >= 5:
                latest_d, latest_v = eps[-1]
                yoy_v = eps[-5][1]
                if yoy_v:
                    out["eps_yoy_pct"] = round((latest_v - yoy_v) / abs(yoy_v) * 100, 1)

        # 最新一季毛利率 / 營益率
        def latest_val(t: str):
            s = _quarterly_series(fs, t)
            return s[-1] if s else None

        rev_q = latest_val("Revenue")
        gp_q = latest_val("GrossProfit")
        oi_q = latest_val("OperatingIncome")
        if rev_q and gp_q and rev_q[0] == gp_q[0] and rev_q[1]:
            out["gross_margin_pct"] = round(gp_q[1] / rev_q[1] * 100, 1)
        if rev_q and oi_q and rev_q[0] == oi_q[0] and rev_q[1]:
            out["operating_margin_pct"] = round(oi_q[1] / rev_q[1] * 100, 1)
        if rev_q:
            out["latest_quarter"] = rev_q[0]

    # 資產負債：負債比 + ROE
    bs = fm.balance_sheet(sid, days=500)
    if not bs.empty:
        liab = _quarterly_series(bs, "Liabilities")
        assets = _quarterly_series(bs, "TotalAssets")
        equity = _quarterly_series(bs, "EquityAttributableToOwnersOfParent") or _quarterly_series(bs, "Equity")
        if liab and assets and liab[-1][0] == assets[-1][0] and assets[-1][1]:
            out["debt_ratio_pct"] = round(liab[-1][1] / assets[-1][1] * 100, 1)
        # ROE(TTM 約略) = TTM 淨利 / 最新股東權益
        if not fs.empty and equity:
            ni = _quarterly_series(fs, "IncomeAfterTaxes")
            if len(ni) >= 4 and equity[-1][1]:
                ttm_ni = sum(v for _, v in ni[-4:])
                out["roe_ttm_pct"] = round(ttm_ni / equity[-1][1] * 100, 1)

    return out


def _valuation_section(sid: str, fundamentals: dict[str, Any], close: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    per = fm.per_pbr(sid, days=30).sort_values("date")
    if not per.empty:
        last = per.iloc[-1]
        out["per"] = float(last["PER"])
        out["pbr"] = float(last["PBR"])
        out["dividend_yield_pct"] = float(last["dividend_yield"])
        # PEG = PER / EPS 年增率(%)
        eps_yoy = fundamentals.get("eps_yoy_pct")
        if eps_yoy and eps_yoy > 0:
            out["peg"] = round(float(last["PER"]) / eps_yoy, 2)
    # 股利（近一年加總 + 年化預估）
    from ..analysis.valuation import dividend_analysis
    out["dividend"] = dividend_analysis(sid, close)
    return out


# --- 對外主函式 -------------------------------------------------------------

def build_snapshot(stock_id: str) -> dict[str, Any]:
    """產生單檔個股研究快照。"""
    price = _safe(lambda: _price_section(stock_id))
    close = price.get("close") if isinstance(price, dict) else None
    chips = _safe(lambda: _chips_section(stock_id))
    fundamentals = _safe(lambda: _fundamentals_section(stock_id))
    valuation = _safe(lambda: _valuation_section(stock_id, fundamentals if isinstance(fundamentals, dict) else {}, close))
    return {
        "stock_id": stock_id,
        "price": price,
        "chips": chips,
        "fundamentals": fundamentals,
        "valuation": valuation,
    }
