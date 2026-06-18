"""基本面估算模組：孫慶龍 8 步驟法
=================================
Step 1 查今年累積營收年增率（前N月 vs 去年同期）
Step 2 查上一年度全年營收
Step 3 預估今年營收 = 上年全年 × (1 + YoY%)
Step 4 假設近四季 TTM 母公司稅後淨利率（用EPS×發行股數/TTM營收推算）
Step 5 預估稅後淨利 = 預估營收 × 淨利率
Step 6 預估 EPS   = 預估稅後淨利 ÷ 發行股數
Step 7 假設近三年盈餘分配率均值
Step 8 預估現金股利 = 預估 EPS × 分配率

資料單位：FinMind 月營收與財報均為 NTD（元），非千元。
發行股數取自股利 ParticipateDistributionOfTotalShares（最準確）。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from src.data import finmind_client as fm


# --- 輔助：NTD 元 → 易讀字串（兆/億）---------------------------------------
def _fmt(val_ntd) -> str:
    """NTD → 兆/億 字串。"""
    if val_ntd is None:
        return "—"
    v = float(val_ntd)
    if abs(v) >= 1e12:
        return f"{v/1e12:.4f}兆"
    elif abs(v) >= 1e8:
        return f"{v/1e8:.1f}億"
    else:
        return f"{v:,.0f}元"


def _roc_to_ad(year_str) -> Optional[int]:
    """民國年字串(如'112年')→ 西元年。"""
    try:
        s = str(year_str).replace("年", "").strip()
        roc = int(s)
        if roc > 1911:  # 已是西元年
            return roc
        return roc + 1911
    except Exception:
        return None


def _series(fs: pd.DataFrame, type_name: str) -> list[tuple[str, float]]:
    sub = fs[fs["type"] == type_name].copy()
    if sub.empty:
        return []
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    return [(str(r["date"])[:10], float(r["value"])) for _, r in sub.iterrows()]


# --- 主計算 -------------------------------------------------------------------
def compute(sid: str) -> dict:
    """執行8步驟計算，回 dict。所有鍵保證存在，算不出時為 None。"""
    today = date.today()
    cur_y = today.year
    prev_y = cur_y - 1

    r: dict = {
        "cur_year": cur_y,
        "prev_year": prev_y,
        # Steps 1-3  (NTD)
        "ytd_months": None,
        "ytd_yoy_pct": None,
        "prev_year_revenue": None,
        "est_revenue": None,
        # Steps 4-6  (NTD)
        "net_margin_ttm_pct": None,
        "net_margin_quarter": None,
        "shares_hundred_million": None,    # 億股
        "est_net_income": None,            # NTD
        "est_eps": None,                   # 元/股
        # Steps 7-8
        "payout_years": [],
        "payout_ratio_avg_pct": None,
        "est_dividend": None,              # 元/股
        "errors": [],
    }

    # ── Steps 1-3：月營收（FinMind revenue 單位：NTD 元）────────────────────
    try:
        rev = fm.month_revenue(sid, days=760)
        if rev.empty:
            r["errors"].append("無月營收資料")
        else:
            rev = rev.copy()
            rev["revenue_year"]  = rev["revenue_year"].astype(int)
            rev["revenue_month"] = rev["revenue_month"].astype(int)
            rev["revenue"] = pd.to_numeric(rev["revenue"], errors="coerce").fillna(0.0)

            curr = rev[rev["revenue_year"] == cur_y]
            prev = rev[rev["revenue_year"] == prev_y]

            if curr.empty:
                r["errors"].append("當年度無月營收資料")
            else:
                max_m = int(curr["revenue_month"].max())
                r["ytd_months"] = max_m
                curr_ytd = float(curr[curr["revenue_month"] <= max_m]["revenue"].sum())
                prev_ytd = float(prev[prev["revenue_month"] <= max_m]["revenue"].sum()) if not prev.empty else 0.0

                if prev_ytd > 0:
                    r["ytd_yoy_pct"] = round((curr_ytd - prev_ytd) / prev_ytd * 100, 2)

                if not prev.empty:
                    prev_full = float(prev["revenue"].sum())
                    if prev_full > 0:
                        r["prev_year_revenue"] = prev_full
                        if r["ytd_yoy_pct"] is not None:
                            r["est_revenue"] = round(prev_full * (1 + r["ytd_yoy_pct"] / 100), 0)
    except Exception as exc:
        r["errors"].append(f"月營收錯誤: {exc}")

    # ── Step 7-8 先跑：用股利取得發行股數（partic. shares 最可靠）──────────
    shares_ntd = None   # 發行股數（股）
    try:
        div = fm.dividend(sid, days=1500)
        fs2 = fm.financial_statements(sid, days=1800)

        if not div.empty:
            div = div.copy()
            div["cash"] = (
                pd.to_numeric(div.get("CashEarningsDistribution", 0), errors="coerce").fillna(0.0)
                + pd.to_numeric(div.get("CashStatutorySurplus", 0), errors="coerce").fillna(0.0)
            )
            # 取最新一筆的發行股數作為基準
            if "ParticipateDistributionOfTotalShares" in div.columns:
                sh_vals = pd.to_numeric(
                    div["ParticipateDistributionOfTotalShares"], errors="coerce"
                ).dropna()
                if not sh_vals.empty:
                    shares_ntd = float(sh_vals.iloc[-1])   # 最近一次除息的參與股數（股）
                    r["shares_hundred_million"] = round(shares_ntd / 1e8, 2)

            # 年度 EPS（四季加總，從財報取）
            annual_eps: dict[int, float] = {}
            if not fs2.empty:
                eps_q = fs2[fs2["type"] == "EPS"].copy()
                if not eps_q.empty:
                    eps_q["date"] = pd.to_datetime(eps_q["date"])
                    eps_q["year"] = eps_q["date"].dt.year
                    eps_q["value"] = pd.to_numeric(eps_q["value"], errors="coerce").fillna(0.0)
                    annual_eps = eps_q.groupby("year")["value"].sum().to_dict()

            # 盈餘分配率（近三年）
            records = []
            if "year" in div.columns:
                div_cash = div[div["cash"] > 0].copy()
                for _, row in div_cash.iterrows():
                    ad_year = _roc_to_ad(row.get("year"))
                    if ad_year is None:
                        continue
                    cash = float(row["cash"])
                    eps_y = annual_eps.get(ad_year)
                    if eps_y and eps_y > 0 and (prev_y - 3) <= ad_year <= prev_y:
                        records.append({
                            "year": ad_year,
                            "cash": round(cash, 2),
                            "eps": round(eps_y, 2),
                            "payout_pct": round(cash / eps_y * 100, 1),
                        })

            records = sorted(records, key=lambda x: x["year"], reverse=True)[:3]
            r["payout_years"] = records
            if records:
                avg = sum(x["payout_pct"] for x in records) / len(records)
                r["payout_ratio_avg_pct"] = round(avg, 1)
    except Exception as exc:
        r["errors"].append(f"股利/股數錯誤: {exc}")

    # ── Steps 4-6：財報淨利率（母公司淨利率 = EPS × 股數 / 營收）───────────
    try:
        fs = fm.financial_statements(sid, days=600)
        if fs.empty:
            r["errors"].append("無財報資料")
        else:
            rev_s = _series(fs, "Revenue")       # 季營收（NTD）
            eps_s = _series(fs, "EPS")            # 季EPS（元/股）

            if len(eps_s) >= 4 and len(rev_s) >= 4:
                ttm_eps = sum(v for _, v in eps_s[-4:])   # 近四季EPS總和
                ttm_rev = sum(v for _, v in rev_s[-4:])   # 近四季營收（NTD）
                r["net_margin_quarter"] = eps_s[-1][0][:7]

                if ttm_rev > 0 and shares_ntd and shares_ntd > 0:
                    # 母公司淨利率 = 近四季EPS × 發行股數 / 近四季營收
                    parent_ni_ttm = ttm_eps * shares_ntd        # NTD
                    r["net_margin_ttm_pct"] = round(parent_ni_ttm / ttm_rev * 100, 2)

                # Steps 5-6
                if r["est_revenue"] and r["net_margin_ttm_pct"] and shares_ntd:
                    est_ni = r["est_revenue"] * r["net_margin_ttm_pct"] / 100   # NTD
                    r["est_net_income"] = round(est_ni, 0)
                    r["est_eps"] = round(est_ni / shares_ntd, 2)

            # Steps 8 （需要 est_eps）
            if r["est_eps"] and r["payout_ratio_avg_pct"]:
                r["est_dividend"] = round(r["est_eps"] * r["payout_ratio_avg_pct"] / 100, 2)

    except Exception as exc:
        r["errors"].append(f"財報錯誤: {exc}")

    return r


# --- 文字摘要（供 demo / 寫檔 / Gemini 用）-----------------------------------
def summary(sid: str, name: str, result: Optional[dict] = None) -> str:
    """產生適合在討論中顯示的文字摘要（8步驟逐行列出）。"""
    if result is None:
        result = compute(sid)
    r = result
    cur_y = r.get("cur_year", date.today().year)
    prev_y = r.get("prev_year", cur_y - 1)
    yoy = r.get("ytd_yoy_pct")
    ytd_m = r.get("ytd_months")

    lines = [f"【{name}({sid}) 基本面估算（孫慶龍8步驟法）】"]

    # Steps 1-3
    if ytd_m:
        lines.append(f"步驟① 今年前{ytd_m}月累積營收年增率：{'—' if yoy is None else f'{yoy:+.2f}%'}")
    if r.get("prev_year_revenue"):
        lines.append(f"步驟② {prev_y}全年營收：{_fmt(r['prev_year_revenue'])}")
    if r.get("est_revenue"):
        yoy_txt = f"×(1{'+' if yoy and yoy >= 0 else ''}{yoy:.2f}%)" if yoy is not None else ""
        lines.append(f"步驟③ 預估{cur_y}全年營收：{_fmt(r['est_revenue'])} {yoy_txt}")

    # Steps 4-6
    if r.get("net_margin_ttm_pct"):
        lines.append(
            f"步驟④ 近四季母公司TTM稅後淨利率：{r['net_margin_ttm_pct']}%"
            f"（截至{r.get('net_margin_quarter','—')}，EPS×發行股數÷TTM營收）"
        )
    if r.get("est_net_income"):
        lines.append(f"步驟⑤ 預估稅後淨利：{_fmt(r['est_net_income'])}")
    if r.get("est_eps") and r.get("shares_hundred_million"):
        lines.append(f"步驟⑥ 預估EPS：{r['est_eps']}元（÷{r['shares_hundred_million']:.2f}億股）")

    # Steps 7-8
    if r.get("payout_years"):
        detail = "、".join(
            f"{x['year']}年(EPS {x['eps']}→現金股利{x['cash']}元,分配率{x['payout_pct']:.1f}%)"
            for x in r["payout_years"]
        )
        lines.append(f"步驟⑦ 近三年盈餘分配率均值：{r.get('payout_ratio_avg_pct')}%（{detail}）")
    if r.get("est_dividend"):
        lines.append(f"步驟⑧ 預估現金股利：{r['est_dividend']}元")

    if r.get("errors"):
        lines.append(f"⚠️ {'; '.join(r['errors'])}")

    lines.append("（依現有公開財報推算，每月營收公告後應重算；非投資建議。）")
    return "\n".join(lines)
