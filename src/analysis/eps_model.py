"""EPS 推估模型（本益比評價法的核心）。

以近四季(TTM)實際財務為基準，給定『預估營收成長率』與『預估毛利率』，
依分析師同款損益鏈推估 forward EPS：

  營收 → 毛利 → −營業費用 → +業外 → 稅前 → ×(1−稅率) → ×歸母佔比 → ÷股數 → EPS

其餘參數（營業費用率、業外、稅率、歸母佔比、股數）取 TTM 實際值。
"""
from __future__ import annotations

from typing import Any

from ..data import finmind_client as fm


def _ttm(df, t: str) -> float | None:
    s = df[df["type"] == t].sort_values("date")
    if len(s) < 4:
        return None
    return float(s.iloc[-4:]["value"].astype(float).sum())


def fundamentals_ttm(sid: str) -> dict[str, Any] | None:
    """回傳推估所需的 TTM 基準參數，資料不足回 None。"""
    fs = fm.financial_statements(sid, days=520)
    if fs.empty:
        return None
    rev = _ttm(fs, "Revenue")
    gp = _ttm(fs, "GrossProfit")
    oi = _ttm(fs, "OperatingIncome")
    pti = _ttm(fs, "PreTaxIncome")
    ni = _ttm(fs, "IncomeAfterTaxes")
    eps = _ttm(fs, "EPS")
    if not rev or rev <= 0 or None in (gp, oi, pti, ni, eps) or pti == 0:
        return None

    shares = None
    bs = fm.balance_sheet(sid, days=520)
    if not bs.empty:
        cap = bs[bs["type"] == "CapitalStock"].sort_values("date")
        if not cap.empty:
            cap_val = float(cap.iloc[-1]["value"])
            if cap_val > 0:
                shares = cap_val / 10.0  # 面額 10 元
    # 用 EPS×股數 回推歸母淨利 → 歸母佔比
    parent_ratio = None
    if shares and ni:
        parent_ni = eps * shares
        parent_ratio = parent_ni / ni if ni else None

    return {
        "rev": rev,
        "gross_margin": gp / rev,
        "opex_ratio": (gp - oi) / rev,
        "nonop": pti - oi,
        "tax_rate": 1 - ni / pti,
        "consol_ni": ni,
        "shares": shares,
        "parent_ratio": parent_ratio,
        "eps_ttm": eps,
        "op_margin": oi / rev,
        "net_margin": ni / rev,
    }


def project_eps(f: dict[str, Any], rev_growth_pct: float, gross_margin_pct: float) -> float | None:
    """給定營收成長率(%)與毛利率(%)，推估 forward EPS。"""
    if not f or not f.get("shares"):
        return None
    rev = f["rev"] * (1 + rev_growth_pct / 100.0)
    gp = rev * (gross_margin_pct / 100.0)
    oi = gp - rev * f["opex_ratio"]
    pti = oi + f["nonop"]
    ni = pti * (1 - f["tax_rate"])
    parent = ni * (f["parent_ratio"] if f.get("parent_ratio") else 1.0)
    return parent / f["shares"]


def eps_sensitivity_to_margin(f: dict[str, Any]) -> float | None:
    """毛利率每 +1 個百分點對 EPS 的影響（元/pp）。"""
    if not f or not f.get("shares"):
        return None
    base = project_eps(f, 0, f["gross_margin"] * 100)
    up = project_eps(f, 0, f["gross_margin"] * 100 + 1)
    if base is None or up is None:
        return None
    return up - base
