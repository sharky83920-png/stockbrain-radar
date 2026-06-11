"""本益比河流圖估價：算個股的 便宜 / 合理 / 昂貴 價。

方法：
- PER 區間用「這檔自己近 N 年」的歷史 PER 分位數（便宜=p20、合理=p50、昂貴=p80）。
- EPS 兩種：①近四季 TTM（用 現價/現PER 反推，確保與歷史 PER 同基準）
            ②預估 EPS = TTM ×(1+成長率)，成長率取近月營收 YoY 平均（capped）。
- 三檔價 = 對應 PER × EPS；再標現價落在哪一區。
免費資料無券商共識 EPS，預估以成長率推估（best-effort、可解釋）。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.data import finmind_client as fm


def per_percentiles(sid: str, years: int = 4) -> dict | None:
    try:
        df = fm.fetch("TaiwanStockPER", sid, (date.today() - timedelta(days=365 * years)).isoformat())
    except Exception:
        return None
    if df.empty or "PER" not in df.columns:
        return None
    per = pd.to_numeric(df["PER"], errors="coerce").dropna()
    per = per[per > 0]
    if len(per) < 30:
        return None
    return {"p20": round(float(per.quantile(0.20)), 1),
            "p50": round(float(per.quantile(0.50)), 1),
            "p80": round(float(per.quantile(0.80)), 1),
            "current": round(float(per.iloc[-1]), 1),
            "years": years, "n": int(len(per))}


def _growth_pct(snap: dict) -> float:
    f = snap.get("fundamentals", {}) or {}
    yoy = f.get("revenue_yoy_recent") or []
    gs = [m["yoy_pct"] for m in yoy if isinstance(m.get("yoy_pct"), (int, float))]
    g = (sum(gs) / len(gs)) if gs else (f.get("eps_yoy_pct") or 0)
    return max(-20.0, min(60.0, float(g)))  # 夾在 -20%~+60%，避免極端外推


def price_bands(sid: str, snap: dict) -> dict | None:
    pe = per_percentiles(sid)
    if not pe or not pe["current"]:
        return None
    price = (snap.get("price", {}) or {}).get("close")
    if not isinstance(price, (int, float)) or not price:
        return None
    ttm_eps = price / pe["current"]          # 與歷史 PER 同基準的 TTM EPS
    g = _growth_pct(snap)
    fwd_eps = ttm_eps * (1 + g / 100)

    def band(eps):
        return {"cheap": round(pe["p20"] * eps), "fair": round(pe["p50"] * eps),
                "expensive": round(pe["p80"] * eps)}

    fwd = band(fwd_eps)
    # 落點用「預估EPS河流圖」（電子股向前看）
    if price < fwd["cheap"]:
        zone = "便宜（低於歷史20分位）"
    elif price < fwd["fair"]:
        zone = "便宜~合理"
    elif price < fwd["expensive"]:
        zone = "合理~昂貴"
    else:
        zone = "昂貴（高於歷史80分位）"
    return {"per": pe, "ttm_eps": round(ttm_eps, 2), "fwd_eps": round(fwd_eps, 2), "growth_pct": round(g, 1),
            "ttm_bands": band(ttm_eps), "fwd_bands": fwd, "price": round(price, 1), "zone": zone}


def brief(sid: str, snap: dict) -> str:
    """給討論/data_brief 用的估價摘要。算不出回空字串。"""
    b = price_bands(sid, snap)
    if not b:
        return ""
    pe, t, f = b["per"], b["ttm_bands"], b["fwd_bands"]
    return (
        f"估價(本益比河流圖, 近{pe['years']}年): 便宜/合理/昂貴 PER = {pe['p20']}/{pe['p50']}/{pe['p80']} 倍（現 {pe['current']} 倍）\n"
        f"  ・用近四季EPS {b['ttm_eps']}：便宜 {t['cheap']} / 合理 {t['fair']} / 昂貴 {t['expensive']}\n"
        f"  ・用預估EPS {b['fwd_eps']}（成長 {b['growth_pct']}%）：便宜 {f['cheap']} / 合理 {f['fair']} / 昂貴 {f['expensive']}\n"
        f"  ・現價 {b['price']} → 落在【{b['zone']}】（以預估EPS河流圖判定）"
    )
