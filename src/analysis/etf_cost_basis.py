"""00878 成分股「推估持股成本」——用持股史 × 歷史股價，移動加權平均法。

原理：ETF 真實成本不公開。用 Phase 1 的每日持股快照，逐日看某檔股數變化：
  - 股數增加 Δ → 視為當日以收盤價買進 Δ 股，更新移動加權平均成本
  - 股數減少   → 以平均成本沖銷（移動平均法，均價不變）
最後得到每檔的推估平均成本，對照現價 → 推估未實現損益。

⚠️ 這是估算，不是基金帳務：
  - 除息日/加碼日的成交價用「當日收盤」近似（非真實成交均價）
  - 每日創造/贖回造成的等比微幅漂移也被算進「買進」→ 結果偏向「持有期間的加權平均市價」
  - 指數換股當天大額建倉才是成本主體；日常漂移只是微調
價格來源：FinMind（一次性快取；涵蓋上市+上櫃）。台股紅漲綠跌 → 損益紅正綠負由 UI 處理。
"""
from __future__ import annotations

import pandas as pd

from ..data import finmind_client as fm
from ..data import etf_holdings as eh


def _price_map(code: str, start_date: str) -> dict[str, float]:
    """{date: close}。FinMind 全歷史一次抓、快取。"""
    df = fm.fetch("TaiwanStockPrice", code, start_date=start_date)
    if df.empty or "close" not in df.columns:
        return {}
    return {str(r.date): float(r.close) for r in df.itertuples(index=False)
            if float(getattr(r, "close", 0) or 0) > 0}


def _share_series(snapshots: dict, code: str) -> list[tuple[str, int]]:
    """該股在倉庫中每個有紀錄日的 (date, shares)，依日期排序。未持有的日子不列。

    snapshots 為預先載入的 {date: [rows]}（避免在迴圈裡重複讀 2.5MB JSON）。
    """
    out = []
    for d in sorted(snapshots):
        for r in snapshots[d]:
            if r["code"] == code:
                out.append((d, int(r["shares"])))
                break
    return out


def estimate_one(fund: str, code: str, snapshots: dict | None = None) -> dict | None:
    """單一成分股的推估成本。查無持股或無價則回 None。"""
    if snapshots is None:
        snapshots = eh.load_store(fund)["snapshots"]
    series = _share_series(snapshots, code)
    if not series:
        return None
    prices = _price_map(code, series[0][0])
    if not prices:
        return None

    def price_on(d: str) -> float | None:
        if d in prices:
            return prices[d]
        earlier = [pd_ for pd_ in prices if pd_ <= d]  # 最近可得的較早收盤
        return prices[max(earlier)] if earlier else None

    shares = 0
    cost = 0.0        # 持有部位的總成本
    buy_cost = 0.0    # 累計買進金額（估算加碼投入）
    buy_shares = 0
    for d, s in series:
        delta = s - shares
        px = price_on(d)
        if px is None:
            shares = s
            continue
        if delta > 0:
            cost += delta * px
            buy_cost += delta * px
            buy_shares += delta
        elif delta < 0 and shares > 0:
            avg = cost / shares
            cost += delta * avg   # 以均價沖銷，均價不變
        shares = s
    if shares <= 0:
        return None

    est_avg_cost = cost / shares
    last_date = max(prices)
    cur_px = prices[last_date]
    return {
        "code": code,
        "shares": shares,
        "est_avg_cost": round(est_avg_cost, 2),
        "current_price": round(cur_px, 2),
        "unreal_pnl_pct": round((cur_px / est_avg_cost - 1) * 100, 1),
        "first_held": series[0][0],
        "vwap_buy_cost": round(buy_cost / buy_shares, 2) if buy_shares else None,
    }


def estimate_cost_basis(fund: str = "00878") -> pd.DataFrame:
    """對『目前持股』每一檔推估成本，回傳含權重、現價、推估成本、未實現損益的 DataFrame。"""
    snapshots = eh.load_store(fund)["snapshots"]   # 只讀一次
    date, latest = eh.latest(fund)
    if latest.empty:
        return pd.DataFrame()
    recs = []
    for r in latest.itertuples(index=False):
        est = estimate_one(fund, r.stock_code, snapshots)
        if est is None:
            continue
        est.update({"name": r.stock_name, "weight": r.weight})
        recs.append(est)
    df = pd.DataFrame(recs)
    cols = ["code", "name", "weight", "shares", "est_avg_cost",
            "current_price", "unreal_pnl_pct", "first_held", "vwap_buy_cost"]
    return df[cols].sort_values("weight", ascending=False, ignore_index=True)
