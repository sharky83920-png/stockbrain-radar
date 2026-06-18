"""多維度估值分析模組
=================================
以孫慶龍 8 步驟法的「預估 EPS」為核心，搭配多維度評價：
  • P/E：保守/中性/樂觀目標價（兩個基準：①這檔自己的歷史 P/E ②同業 P/E）
  • PEG：用「真實 EPS 年增率」算公允價與當前 PEG（Peter Lynch，PEG=1 為公允）
  • P/CF：當前股價 ÷ 近四季每股自由現金流（檢查獲利是否有現金支撐）
  • 投顧共識：讀知識庫投顧報告，反推目標價隱含 P/E

⚠️ 原則：所有數字都來自真實資料（FinMind / 自家財報 / 投顧報告），不憑空填。
   每個函式回傳的 dict 都帶 `source` / `basis` 文字，供 UI 顯示「怎麼算的」。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np
import pandas as pd

from src.data import finmind_client as fm
from src.data import cache
from src.analysis import fundamental_forecast as ff
from src.analysis import valuation as val


# ── 核心：孫慶龍 8 步驟法 ───────────────────────────────────────────────
def get_fundamental_forecast(sid: str) -> Dict:
    """取得孫慶龍 8 步驟法的基本面估算結果（含 est_eps）。"""
    return ff.compute(sid)


# ── P/E 基準（一）：這檔自己的歷史 P/E 百分位 ──────────────────────────
def historical_pe_basis(sid: str, years: int = 3) -> Optional[Dict]:
    """用 valuation.pe_band 取這檔近 N 年每日 P/E 的 20/50/80 百分位，
    當保守/中性/樂觀倍數。全部真實，無爬蟲。"""
    band = val.pe_band(sid, years=years, percentiles=(20, 50, 80))
    mults = band.get("multiples") or []
    if len(mults) < 2:
        return None
    mults = sorted(mults)
    if len(mults) >= 3:
        conservative, neutral, optimistic = mults[0], mults[1], mults[-1]
    else:  # 只剩兩檔（百分位數值碰撞）
        conservative, optimistic = mults[0], mults[-1]
        neutral = round((conservative + optimistic) / 2, 1)
    return {
        "conservative": conservative,
        "neutral": neutral,
        "optimistic": optimistic,
        "current_per": band.get("current_per"),
        "source": f"近{years}年歷史 P/E 百分位(20/50/80)",
    }


# ── P/E 基準（二）：同業 P/E ────────────────────────────────────────────
def _pick_industry(sid: str, info: pd.DataFrame) -> Optional[tuple]:
    """挑最具代表性的產業：取這檔所屬類別中『成員數最少（最細）』者。
    回傳 (industry_name, peer_ids)。"""
    rows = info[info["stock_id"] == sid]
    if rows.empty:
        return None
    best = None
    for c in rows["industry_category"].dropna().unique():
        peers = info[info["industry_category"] == c]["stock_id"].unique().tolist()
        if len(peers) < 2:
            continue
        if best is None or len(peers) < len(best[1]):
            best = (str(c), peers)
    return best


def industry_pe_basis(sid: str, sample: int = 30) -> Optional[Dict]:
    """同業 P/E 基準。從 FinMind 取同產業成員，抽樣計算當前 P/E 的 25/50/75
    百分位（中位數抗離群），當保守/中性/樂觀倍數。結果以「產業」為單位快取 1 天。

    註：免費資料源無『一次取全市場 P/E』的端點（需逐檔查），故取樣本上限 sample
    檔並以中位數呈現；UI 會標示實際採用檔數。Goodinfo 同業頁在伺服器端被反爬封鎖
    （回傳 1KB 擋頁），因此改用 FinMind 真實資料而非爬 Goodinfo。"""
    try:
        info = fm.all_stock_info()
    except Exception:
        return None
    picked = _pick_industry(sid, info)
    if not picked:
        return None
    industry, peers = picked

    ck = f"industry_pe|{industry}|{sample}"
    cached = cache.get(ck, max_age_days=1)
    if cached:
        return cached[0] if isinstance(cached, list) and cached else cached

    # 確保自己在樣本內，其餘依序取至上限
    sample_ids = [sid] + [p for p in peers if p != sid]
    sample_ids = sample_ids[:sample]

    pers: List[float] = []
    for pid in sample_ids:
        try:
            p = fm.per_pbr(pid, days=10)
            if p.empty:
                continue
            v = pd.to_numeric(p["PER"], errors="coerce").dropna()
            v = v[(v > 0) & (v < 200)]
            if not v.empty:
                pers.append(float(v.iloc[-1]))
        except Exception:
            continue

    if len(pers) < 3:
        return None

    arr = np.array(pers)
    out = {
        "industry": industry,
        "peer_count": len(peers),
        "sample_used": len(pers),
        "conservative": round(float(np.percentile(arr, 25)), 1),
        "neutral": round(float(np.percentile(arr, 50)), 1),
        "optimistic": round(float(np.percentile(arr, 75)), 1),
        "source": f"同業「{industry}」P/E（FinMind {len(pers)}/{len(peers)} 檔樣本，25/50/75 百分位）",
    }
    cache.put(ck, [out])
    return out


# ── 真實 EPS 年增率（給 PEG 用，取代原本亂編的 18%）────────────────────
def _annual_eps(sid: str) -> tuple[dict, dict]:
    """從財報取年度 EPS（四季加總）與各年度季數。"""
    fs = fm.financial_statements(sid, days=1800)
    if fs.empty:
        return {}, {}
    eps = fs[fs["type"] == "EPS"].copy()
    if eps.empty:
        return {}, {}
    eps["date"] = pd.to_datetime(eps["date"])
    eps["year"] = eps["date"].dt.year
    eps["value"] = pd.to_numeric(eps["value"], errors="coerce").fillna(0.0)
    annual = eps.groupby("year")["value"].sum().to_dict()
    counts = eps.groupby("year")["value"].count().to_dict()
    return annual, counts


def eps_growth_real(sid: str, est_eps: Optional[float] = None) -> Dict:
    """真實 EPS 年增率。
    forward：預估EPS（孫慶龍）vs 最近一個完整年度實際 EPS。
    hist：最近兩個完整年度的實際年增率。
    PEG 優先用 forward，無則用 hist。"""
    annual, counts = _annual_eps(sid)
    out = {
        "forward_growth_pct": None,
        "hist_growth_pct": None,
        "growth_for_peg": None,
        "last_year": None,
        "last_annual_eps": None,
        "basis": None,
    }
    complete = sorted(y for y, c in counts.items() if c >= 4)
    if not complete:
        return out

    ly = complete[-1]
    le = annual.get(ly)
    out["last_year"] = int(ly)
    out["last_annual_eps"] = round(le, 2) if le is not None else None

    if est_eps and le and le > 0:
        out["forward_growth_pct"] = round((est_eps / le - 1) * 100, 1)
    if len(complete) >= 2:
        py, pe = complete[-2], annual.get(complete[-2])
        if pe and pe > 0 and le is not None:
            out["hist_growth_pct"] = round((le / pe - 1) * 100, 1)

    if out["forward_growth_pct"] is not None:
        out["growth_for_peg"] = out["forward_growth_pct"]
        out["basis"] = f"預估EPS {est_eps} vs {ly}年實際 {out['last_annual_eps']} → {out['forward_growth_pct']:+.1f}%"
    elif out["hist_growth_pct"] is not None:
        out["growth_for_peg"] = out["hist_growth_pct"]
        out["basis"] = f"{complete[-2]}→{complete[-1]}年實際EPS年增 {out['hist_growth_pct']:+.1f}%"
    return out


# ── 每股自由現金流（P/CF 用）──────────────────────────────────────────
def _ttm_from_cumulative(sub: pd.DataFrame) -> Optional[float]:
    """FinMind 現金流量表為年度累計（YTD）。先還原成單季，再加總近四季 = TTM。"""
    if sub.empty:
        return None
    sub = sub.sort_values("date").copy()
    sub["year"] = sub["date"].dt.year
    quarters: list[tuple] = []
    for _, g in sub.groupby("year"):
        g = g.sort_values("date")
        prev = 0.0
        for _, row in g.iterrows():
            quarters.append((row["date"], float(row["value"]) - prev))
            prev = float(row["value"])
    quarters.sort(key=lambda x: x[0])
    if len(quarters) < 4:
        return None
    return sum(v for _, v in quarters[-4:])


def fcf_per_share(sid: str, shares_ntd: Optional[float]) -> Optional[Dict]:
    """近四季每股自由現金流 FCF/股 = (營業現金流 − 資本支出) ÷ 發行股數。
    FinMind 現金流為 YTD 累計，已還原單季再加總 TTM。"""
    if not shares_ntd or shares_ntd <= 0:
        return None
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

    op = _ttm_from_cumulative(cf[cf["type"] == "CashFlowsFromOperatingActivities"])
    if op is None:
        op = _ttm_from_cumulative(cf[cf["type"] == "NetCashInflowFromOperatingActivities"])
    capex = _ttm_from_cumulative(cf[cf["type"] == "PropertyAndPlantAndEquipment"])
    if op is None:
        return None

    fcf = op - abs(capex if capex is not None else 0.0)
    return {
        "fcf_ttm": round(fcf, 0),
        "fcf_per_share": round(fcf / shares_ntd, 2),
        "op_cf_ttm": round(op, 0),
        "capex_ttm": round(abs(capex), 0) if capex is not None else None,
    }


# ── 純計算工具 ──────────────────────────────────────────────────────────
def calculate_pe_valuation(est_eps: Optional[float], pe_multiple: Optional[float]) -> Optional[float]:
    """P/E 估值：目標價 = 預估EPS × P/E倍數。"""
    if not est_eps or not pe_multiple:
        return None
    return round(est_eps * pe_multiple, 2)


def calculate_peg(pe_multiple: Optional[float], eps_growth_pct: Optional[float]) -> Optional[float]:
    """PEG = P/E ÷ 年增率(%)。<0.8 極度低估、0.8-1.0 低估、1.0-1.5 合理、>1.5 昂貴。"""
    if not pe_multiple or not eps_growth_pct or eps_growth_pct <= 0:
        return None
    return round(pe_multiple / eps_growth_pct, 2)


def pe_targets(est_eps: Optional[float], basis: Optional[Dict]) -> Optional[Dict]:
    """把一組 P/E 基準（保守/中性/樂觀倍數）× 預估EPS 變成三檔目標價。"""
    if not est_eps or not basis:
        return None
    return {
        "conservative": calculate_pe_valuation(est_eps, basis.get("conservative")),
        "neutral": calculate_pe_valuation(est_eps, basis.get("neutral")),
        "optimistic": calculate_pe_valuation(est_eps, basis.get("optimistic")),
        "multiples": {
            "conservative": basis.get("conservative"),
            "neutral": basis.get("neutral"),
            "optimistic": basis.get("optimistic"),
        },
        "source": basis.get("source"),
    }


def _signal(current_price: float, neutral_target: Optional[float]) -> Optional[str]:
    if not neutral_target or not current_price:
        return None
    if current_price < neutral_target:
        return f"🔴 買進（現價 {current_price:.0f} < 中性目標 {neutral_target:.0f}）"
    if current_price > neutral_target * 1.1:
        return f"🟢 偏貴（現價 {current_price:.0f} > 中性目標 {neutral_target:.0f} 的110%）"
    return f"🟡 持有（現價 {current_price:.0f} ≈ 中性目標 {neutral_target:.0f}）"


# ── 讀知識庫投顧報告（.md，純文字解析，不需 Gemini）────────────────────
# 報告位置：<知識庫>/個股/<代號>_<名稱>/投顧報告/<券商>_<日期>.md
_KB_CANDIDATES = [
    os.environ.get("STOCKBRAIN_KB_DIR"),
    r"G:\我的雲端硬碟\stockbrain\知識庫",
    r"G:\我的雲端硬碟\secondbrain\創作庫\光之國度自動代理人計畫\知識庫",
]
# 目標價（排除「前次/原」目標價）
_TP_RE = re.compile(r"((?:前次|原)?)\s*目標價[^0-9]{0,6}([0-9][0-9,]*\.?[0-9]*)\s*元")
# 「EPS 30.5 元」這種有單位的預估值（避開表格純數字與「17 位元」）
_EPS_RE = re.compile(r"EPS[^0-9元]{0,8}([0-9]+\.[0-9]+|[0-9]+)\s*元")
_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _kb_report_dirs(sid: str) -> List[Path]:
    """找出所有候選知識庫中該股的『投顧報告』資料夾。"""
    out = []
    for cand in _KB_CANDIDATES:
        if not cand:
            continue
        base = Path(cand) / "個股"
        if not base.exists():
            continue
        try:
            folder = next((d for d in base.iterdir()
                           if d.is_dir() and d.name.split("_")[0] == sid), None)
        except Exception:
            folder = None
        if folder and (folder / "投顧報告").exists():
            out.append(folder / "投顧報告")
    return out


def _parse_report(text: str, fname: str) -> Optional[Dict]:
    """從單一報告檔解析 {source, date, target_price, est_eps}。"""
    stem = Path(fname).stem
    parts = stem.split("_")
    source = parts[0] if parts else stem
    # 日期：先看檔名，再看內文
    fdate = next((p for p in parts if _DATE_RE.fullmatch(p)), None)
    m_date = _DATE_RE.search(text)
    rdate = fdate or (m_date.group(1) if m_date else None)

    # 目標價：取第一個非「前次/原」的命中
    target = None
    for m in _TP_RE.finditer(text):
        if m.group(1):  # 前次/原 → 跳過
            continue
        try:
            target = float(m.group(2).replace(",", ""))
            break
        except ValueError:
            continue
    if not target:
        return None

    est_eps = None
    m_eps = _EPS_RE.search(text)
    if m_eps:
        try:
            est_eps = float(m_eps.group(1))
        except ValueError:
            est_eps = None

    return {"source": source, "date": rdate, "target_price": target, "est_eps": est_eps}


def load_advisor_reports(sid: str) -> List[Dict]:
    """讀該股所有投顧報告 .md，回 [{source,date,target_price,est_eps}]。
    純文字解析（券商與日期取自檔名 <券商>_<日期>.md），不需 GEMINI_KEY。"""
    reports: List[Dict] = []
    for d in _kb_report_dirs(sid):
        for p in sorted(d.glob("*.md")) + sorted(d.glob("*.txt")):
            if p.name.startswith(("_放這裡", "_系統自動")):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            parsed = _parse_report(text, p.name)
            if parsed:
                reports.append(parsed)
    return reports


# ── 投顧報告反推 ────────────────────────────────────────────────────────
def analyze_advisor_targets(advisor_reports: list, own_est_eps: Optional[float] = None) -> Dict:
    """從投顧報告反推平均 P/E。

    輸入：[{"source","target_price","est_eps"(可選),"date"(可選)}, ...]
    隱含 P/E：優先用報告自己的 est_eps；沒有就用我們孫慶龍的 own_est_eps（並標示）。
    """
    empty = {"avg_pe": None, "avg_target_price": None, "count": 0, "details": []}
    if not advisor_reports:
        return empty

    valid = []
    for r in advisor_reports:
        tp = r.get("target_price")
        if not tp or tp <= 0:
            continue
        eps_used = r.get("est_eps")
        eps_src = "報告"
        if not (eps_used and eps_used > 0):
            eps_used, eps_src = own_est_eps, "孫慶龍"
        pe = round(tp / eps_used, 2) if eps_used and eps_used > 0 else None
        valid.append({
            "source": r.get("source", "未知"),
            "date": r.get("date"),
            "target_price": round(float(tp), 2),
            "est_eps": round(float(eps_used), 2) if eps_used else None,
            "eps_src": eps_src,
            "pe": pe,
        })

    if not valid:
        return empty

    pes = [v["pe"] for v in valid if v["pe"] is not None]
    return {
        "avg_pe": round(sum(pes) / len(pes), 2) if pes else None,
        "avg_target_price": round(sum(v["target_price"] for v in valid) / len(valid), 2),
        "count": len(valid),
        "details": sorted(valid, key=lambda x: (x["pe"] is None, x["pe"] or 0), reverse=True),
    }


# ── 總成：多維度估值報告（全真實資料）─────────────────────────────────
def generate_valuation_report(sid: str, current_price: Optional[float],
                              advisor_reports: list = None) -> Dict:
    """生成完整多維度估值報告。所有數字皆來自真實資料源。"""
    fund = get_fundamental_forecast(sid)
    est_eps = fund.get("est_eps")
    shares_ntd = (fund.get("shares_hundred_million") or 0) * 1e8 or None

    current_per = round(current_price / est_eps, 2) if (current_price and est_eps and est_eps > 0) else None

    # 兩個 P/E 基準
    hist_basis = historical_pe_basis(sid)
    ind_basis = industry_pe_basis(sid)

    # 真實 EPS 年增率 → PEG
    growth = eps_growth_real(sid, est_eps)
    g = growth.get("growth_for_peg")

    targets: Dict = {}
    tp_hist = pe_targets(est_eps, hist_basis)
    tp_ind = pe_targets(est_eps, ind_basis)
    if tp_hist:
        targets["pe_historical"] = tp_hist
    if tp_ind:
        targets["pe_industry"] = tp_ind

    # PEG 公允價（Peter Lynch：PEG=1 → 公允 P/E = 年增率）
    # 注意：PEG 法只在中速成長(約 10-40%)可靠；成長過高時 PEG=1 公允價會嚴重高估，
    # 故 >40% 時不給公允價，只保留「當前 PEG」這個相對便宜/貴的訊號。
    peg_block = None
    if est_eps and g and g > 0:
        reliable = g <= 40
        peg_block = {
            "fair_pe": round(g, 1),
            "fair_price": calculate_pe_valuation(est_eps, g) if reliable else None,
            "current_peg": calculate_peg(current_per, g),          # 當前 PEG（相對便宜/貴）
            "growth_pct": g,
            "reliable": reliable,
            "basis": growth.get("basis"),
            "note": None if reliable else f"成長率 {g:.0f}% 過高，PEG=1 公允價失真，僅供參考當前 PEG",
        }
        targets["peg"] = peg_block

    # P/CF：當前每股自由現金流 & 當前 P/CF
    pcf = fcf_per_share(sid, shares_ntd)
    pcf_block = None
    if pcf:
        fps = pcf.get("fcf_per_share")
        pcf_block = {
            **pcf,
            "current_pcf": round(current_price / fps, 2) if (current_price and fps and fps > 0) else None,
            "note": None if (fps and fps > 0) else "近四季自由現金流為負，本流法不適用（獲利暫無現金支撐）",
        }

    # 投顧共識（未指定就自動讀知識庫報告）
    if advisor_reports is None:
        advisor_reports = load_advisor_reports(sid)
    advisor = analyze_advisor_targets(advisor_reports or [], own_est_eps=est_eps)
    if advisor.get("avg_target_price"):
        targets["advisor_consensus"] = advisor["avg_target_price"]

    # 買賣信號（以歷史中性目標為主，無則同業中性）
    ref_neutral = (tp_hist or {}).get("neutral") or (tp_ind or {}).get("neutral")
    signal = _signal(current_price, ref_neutral) if current_price else None

    return {
        "sid": sid,
        "fundamental": fund,
        "current_price": current_price,
        "est_eps": est_eps,
        "current_per": current_per,
        "historical_basis": hist_basis,
        "industry_basis": ind_basis,
        "growth": growth,
        "pcf": pcf_block,
        "advisor_analysis": advisor,
        "targets": targets,
        "signal": signal,
    }
