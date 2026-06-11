"""🔍 選股雷達：拿使用者 SOP 掃候選池，挑出「分數高、但還沒追蹤」的新標的。

評分對齊 SOP：一票否決 → 基本面(40) + 籌碼(25)。
技術(20)/題材(15) 需即時線型與題材判斷，掃描階段資料不足 → 不計、明示。
全程不呼叫 Gemini（省錢），只用 FinMind snapshot。
"""
from __future__ import annotations

from src.data import candidates, watchlist
from src.data import finmind_client as fm
from src.data.snapshot import build_snapshot


def _veto(snap: dict) -> str | None:
    """一票否決：回淘汰原因字串，過關回 None。"""
    f = snap.get("fundamentals", {}) or {}
    p = snap.get("price", {}) or {}
    eps = f.get("eps_ttm")
    if isinstance(eps, (int, float)) and eps <= 0:
        return "近四季 EPS≤0（虧損/無 EPS）"
    vol = p.get("volume_lots")
    if isinstance(vol, (int, float)) and vol < 1000:
        return f"流動性低（日量 {vol} 張 < 1000）"
    return None  # 中國概念/市值<50億 免費資料難自動判，留給使用者複查


def score_one(sid: str, name: str | None = None) -> dict:
    """評一檔：回 {sid,name,score,max,veto,reasons}。max=65（基本面40+籌碼25）。"""
    snap = build_snapshot(sid)
    nm = name or fm.stock_name(sid) or sid
    veto = _veto(snap)
    if veto:
        return {"sid": sid, "name": nm, "score": 0, "max": 65, "veto": veto, "reasons": []}

    f = snap.get("fundamentals", {}) or {}
    c = snap.get("chips", {}) or {}
    score = 0
    reasons: list[str] = []

    # 基本面 40
    roe = f.get("roe_ttm_pct")
    if isinstance(roe, (int, float)) and roe > 12:
        score += 10; reasons.append(f"ROE {roe}%>12 (+10)")
    detail = f.get("three_rates_detail", {}) or {}
    if detail.get("gross"):
        score += 10; reasons.append("毛利率上升 (+10)")
    yoy = f.get("revenue_yoy_recent") or []
    if yoy and all(isinstance(m.get("yoy_pct"), (int, float)) and m["yoy_pct"] > 20 for m in yoy):
        score += 10; reasons.append("月營收年增連>20% (+10)")
    debt = f.get("debt_ratio_pct")
    if isinstance(debt, (int, float)) and debt < 50:
        score += 10; reasons.append(f"負債比 {debt}%<50 (+10)")

    # 籌碼 25
    fn = c.get("foreign_net_20d_lots")
    if isinstance(fn, (int, float)) and fn > 0:
        score += 10; reasons.append(f"外資20日淨買 {fn:,.0f}張 (+10)")
    tn = c.get("trust_net_20d_lots")
    if isinstance(tn, (int, float)) and tn > 0:
        score += 10; reasons.append(f"投信20日淨買 {tn:,.0f}張 (+10)")
    mc = c.get("margin_change_lots")
    if isinstance(mc, (int, float)) and mc < 0:
        score += 5; reasons.append("融資減少(散戶退) (+5)")

    return {"sid": sid, "name": nm, "score": score, "max": 65, "veto": None, "reasons": reasons}


def screen(top_n: int = 10, exclude_watchlist: bool = True) -> list[dict]:
    """掃候選池，回排序後的結果（已追蹤的可排除）。"""
    held = {i["sid"] for i in watchlist.load()} if exclude_watchlist else set()
    out = []
    for sid in candidates.load():
        if sid in held:
            continue
        try:
            out.append(score_one(sid))
        except Exception as e:  # noqa: BLE001
            out.append({"sid": sid, "name": sid, "score": -1, "max": 65,
                        "veto": f"評分失敗:{type(e).__name__}", "reasons": []})
    passed = [r for r in out if r["veto"] is None]
    passed.sort(key=lambda r: r["score"], reverse=True)
    return passed[:top_n]
