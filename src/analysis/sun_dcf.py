"""孫慶龍估值法：現金流量折現（DCF）＋ 現金報酬率
=================================
出處：《超前部署賺好股》第 4 篇「學會計算價格 抓準進場時機」
（整理筆記：知識庫/書籍筆記/超前部署賺好股/孫慶龍企業估值方法總整理.md）

DCF（內在價值法）：
  盈餘成長率 = 近 5 年平均 ROE × (1 − 近 5 年平均盈餘分配率)
  折現率     = 無風險利率（30 年公債）＋ 風險貼水（無對手 5%／競爭多 10%~15%）
  每股企業價值 = 每股淨值 ＋ Σ 未來 20 年 EPS 折現
               （書中台積電表 4 做法：前 10 年全速成長，第 11~20 年成長減半）
  買進價 = 10 年回收價（隱含年化 7.2%）；長期賣出目標 = 20 年回收價（3.55%）
  5 年回收價（14.9%）供積極型要求參考。

現金報酬率（財務比率法中作者首選）：
  = (自由現金流量 ＋ 利息費用) ÷ 完全持有企業的財務成本
  完全持有成本 = 市值 ＋ 長期負債（含公司債）− 現金及約當現金

⚠️ 原則：所有數字來自 FinMind 真實財報，不憑空填；回傳 dict 附 basis/notes 說明。
"""
from __future__ import annotations

import re
from typing import Dict, Optional

import pandas as pd

from src.data import finmind_client as fm
from src.analysis.multidim_valuation import _ttm_from_cumulative

# 書中「回收年數 ↔ 隱含年化報酬率」對照（表1/表2 年化報酬率欄）
PAYBACK_IRR = {5: 14.9, 10: 7.2, 20: 3.55}


def _annual_eps_complete(sid: str, years_back: int = 7) -> dict[int, float]:
    """完整年度（滿 4 季）的年 EPS。"""
    fs = fm.financial_statements(sid, days=years_back * 365)
    if fs.empty:
        return {}
    eps = fs[fs["type"] == "EPS"].copy()
    if eps.empty:
        return {}
    eps["date"] = pd.to_datetime(eps["date"])
    eps["year"] = eps["date"].dt.year
    eps["value"] = pd.to_numeric(eps["value"], errors="coerce").fillna(0.0)
    g = eps.groupby("year")["value"].agg(["sum", "count"])
    return {int(y): float(r["sum"]) for y, r in g.iterrows() if r["count"] >= 4}


def _bs_value(bs: pd.DataFrame, date_str: str, type_names: list[str]) -> Optional[float]:
    sub = bs[bs["date"] == date_str]
    for t in type_names:
        row = sub[sub["type"] == t]
        if not row.empty:
            v = pd.to_numeric(row.iloc[0]["value"], errors="coerce")
            if pd.notna(v):
                return float(v)
    return None


def _cash_dividends_by_fy(sid: str) -> dict[int, float]:
    """每股現金股利（盈餘分配），以『盈餘所屬年度』為 key（FinMind year 為民國年）。"""
    try:
        div = fm.dividend(sid, days=3000)
    except Exception:
        return {}
    if div.empty or "CashEarningsDistribution" not in div.columns:
        return {}
    out: dict[int, float] = {}
    for _, r in div.iterrows():
        # year 可能是「113年」或季配息的「113年第1季」→ 取開頭民國年，同年度各季加總
        m = re.match(r"\s*(\d+)", str(r["year"]))
        if not m:
            continue
        fy = int(m.group(1)) + 1911
        cash = pd.to_numeric(r.get("CashEarningsDistribution"), errors="coerce")
        if pd.notna(cash) and cash > 0:
            out[fy] = out.get(fy, 0.0) + float(cash)
    return out


def gather_dcf_inputs(sid: str, avg_years: int = 5) -> Optional[Dict]:
    """收集 DCF 的 5 大財務數據：ROE、盈餘分配率（各取近 5 年平均）、基期 EPS、每股淨值。"""
    annual_eps = _annual_eps_complete(sid)
    if not annual_eps:
        return None
    years = sorted(annual_eps)[-avg_years:]
    eps0_year = years[-1]
    eps0 = annual_eps[eps0_year]
    if eps0 <= 0:
        return {"error": f"最近完整年度（{eps0_year}）EPS 為負，DCF 不適用虧損公司。"}

    bs = fm.balance_sheet(sid, days=(avg_years + 2) * 365)
    if bs.empty:
        return None
    bs = bs.copy()
    bs["value"] = pd.to_numeric(bs["value"], errors="coerce")

    _EQ = ["EquityAttributableToOwnersOfParent", "Equity"]

    # 各年度 ROE = 年EPS ÷ 年底每股淨值（年底 BVPS = 歸屬母公司權益 ÷ 股數，股數 = 股本/10）
    # FinMind 資產負債表偶有缺季，年底那季沒資料時改用該年度最後一筆可用季度近似
    bs_dates = sorted(bs["date"].unique())
    roe_rows = []
    for y in years:
        y_dates = [d for d in bs_dates if str(d).startswith(str(y))]
        if not y_dates:
            continue
        d_use = y_dates[-1]
        eq = _bs_value(bs, d_use, _EQ)
        cap = _bs_value(bs, d_use, ["CapitalStock"])
        if not eq or not cap or cap <= 0:
            continue
        bvps = eq / (cap / 10.0)
        if bvps > 0:
            roe_rows.append({"year": y, "eps": annual_eps[y],
                             "bvps": round(bvps, 2),
                             "roe_pct": round(annual_eps[y] / bvps * 100, 2)})
    if len(roe_rows) < 3:
        return {"error": f"年底淨值資料不足（僅 {len(roe_rows)} 年），無法穩定估 ROE。"}

    # 各年度盈餘分配率 = 每股現金股利 ÷ 當年 EPS
    cash_div = _cash_dividends_by_fy(sid)
    payout_rows = []
    for r in roe_rows:
        y = r["year"]
        d = cash_div.get(y)
        if d is not None and annual_eps[y] > 0:
            ratio = min(d / annual_eps[y] * 100, 100.0)
            payout_rows.append({"year": y, "cash_div": round(d, 2),
                                "payout_pct": round(ratio, 2)})

    roe_avg = sum(r["roe_pct"] for r in roe_rows) / len(roe_rows)
    payout_avg = (sum(r["payout_pct"] for r in payout_rows) / len(payout_rows)) if payout_rows else None
    notes = []
    if payout_avg is None:
        payout_avg = 0.0
        notes.append("查無現金股利資料，盈餘分配率以 0% 計（成長率會偏高，請留意）。")

    growth_pct = roe_avg * (1 - payout_avg / 100)

    # 最新每股淨值（最新一季）
    latest_date = bs["date"].max()
    eq_now = _bs_value(bs, latest_date, _EQ)
    cap_now = _bs_value(bs, latest_date, ["CapitalStock"])
    if not eq_now or not cap_now or cap_now <= 0:
        return {"error": "取不到最新每股淨值。"}
    shares_now = cap_now / 10.0
    bvps_now = eq_now / shares_now

    return {
        "sid": sid,
        "eps0": round(eps0, 2),
        "eps0_year": eps0_year,
        "bvps": round(bvps_now, 2),
        "bvps_date": latest_date,
        "shares": shares_now,
        "roe_avg_pct": round(roe_avg, 2),
        "payout_avg_pct": round(payout_avg, 2) if payout_avg else 0.0,
        "growth_pct": round(growth_pct, 2),
        "roe_rows": roe_rows,
        "payout_rows": payout_rows,
        "basis": (f"ROE/分配率取 {'、'.join(str(r['year']) for r in roe_rows)} 共 {len(roe_rows)} 年平均；"
                  f"基期 EPS 用 {eps0_year} 全年；淨值為 {latest_date} 歸屬母公司權益÷股數"),
        "notes": notes,
    }


def dcf_table(inputs: Dict, risk_free_pct: float = 4.5, risk_premium_pct: float = 10.0,
              years: int = 20, full_growth_years: int = 10) -> Dict:
    """依書中做法產出 20 年折現表與三檔價位（5 年/10 年/20 年回收價）。

    前 full_growth_years 年以完整成長率複利，之後成長率減半（書中台積電表 4 做法，
    避免高成長無限外推）。折現率 = 無風險利率 ＋ 風險貼水。
    """
    g = inputs["growth_pct"] / 100.0
    r = (risk_free_pct + risk_premium_pct) / 100.0
    eps = inputs["eps0"]
    cum = inputs["bvps"]
    rows = []
    prices: dict[int, float] = {}
    for n in range(1, years + 1):
        eps = eps * (1 + (g if n <= full_growth_years else g / 2))
        disc = eps / (1 + r) ** n
        cum += disc
        rows.append({"年": n, "EPS(元)": round(eps, 2),
                     "折現價(元)": round(disc, 2), "企業價值累計(元)": round(cum, 2)})
        if n in PAYBACK_IRR:
            prices[n] = round(cum, 2)
    return {
        "rows": rows,
        "discount_rate_pct": round(risk_free_pct + risk_premium_pct, 2),
        "price_5y": prices.get(5),      # 積極買點（隱含年化 14.9%）
        "buy_price": prices.get(10),    # 書中買進價 = 10 年回收（隱含年化 7.2%）
        "sell_price": prices.get(20),   # 長期賣出目標 = 20 年回收
        "payback_irr": PAYBACK_IRR,
    }


def cash_return(sid: str, current_price: Optional[float]) -> Optional[Dict]:
    """現金報酬率 = (自由現金流量 TTM ＋ 利息費用 TTM) ÷ (市值 ＋ 長期負債 − 現金)。"""
    if not current_price or current_price <= 0:
        return None
    bs = fm.balance_sheet(sid, days=400)
    if bs.empty:
        return None
    bs = bs.copy()
    bs["value"] = pd.to_numeric(bs["value"], errors="coerce")
    latest = bs["date"].max()
    cap = _bs_value(bs, latest, ["CapitalStock"])
    cash = _bs_value(bs, latest, ["CashAndCashEquivalents"]) or 0.0
    lt_borrow = _bs_value(bs, latest, ["LongtermBorrowings"]) or 0.0
    bonds = _bs_value(bs, latest, ["BondsPayable"]) or 0.0
    if not cap or cap <= 0:
        return None
    shares = cap / 10.0
    mcap = current_price * shares
    cost = mcap + lt_borrow + bonds - cash
    if cost <= 0:
        return {"error": "市值加長債仍低於帳上現金（成本為負），此法不適用。"}

    try:
        cf = fm.cash_flow(sid, days=900)
    except Exception:
        return None
    if cf.empty:
        return None
    cf = cf.copy()
    cf["date"] = pd.to_datetime(cf["date"])
    cf["value"] = pd.to_numeric(cf["value"], errors="coerce")
    cf = cf.dropna(subset=["value"])
    op = (_ttm_from_cumulative(cf[cf["type"] == "CashFlowsFromOperatingActivities"])
          or _ttm_from_cumulative(cf[cf["type"] == "NetCashInflowFromOperatingActivities"]))
    capex = _ttm_from_cumulative(cf[cf["type"] == "PropertyAndPlantAndEquipment"])
    interest = _ttm_from_cumulative(cf[cf["type"] == "InterestExpense"])
    if op is None:
        return None
    fcf = op - abs(capex if capex is not None else 0.0)
    numerator = fcf + abs(interest if interest is not None else 0.0)

    return {
        "cash_return_pct": round(numerator / cost * 100, 2),
        "fcf_ttm": fcf,
        "interest_ttm": abs(interest) if interest is not None else None,
        "mcap": mcap,
        "lt_debt": lt_borrow + bonds,
        "cash": cash,
        "cost": cost,
        "bs_date": latest,
        "basis": (f"市值 = 現價 {current_price} × 股數；長債含公司債；"
                  f"資產負債表基準日 {latest}。FCF/利息為近四季（YTD 已還原單季加總）。"),
    }
