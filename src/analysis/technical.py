"""技術指標計算：ATR（平均真實波幅）。

使用 Wilder's RMA 平滑（與 TradingView 預設一致）。
資料來源：FinMind TaiwanStockPrice（日 K）。
"""
from __future__ import annotations

import pandas as pd

from src.data import finmind_client as fm


def calc_atr(sid: str, period: int = 14, days: int = 60) -> dict:
    """計算 ATR(14) 並回傳止損參考。

    Returns:
        {
            "atr": float,           # 當前 ATR 值（元）
            "close": float,         # 最新收盤價
            "date": str,            # 最新資料日
            "stop_1x": float,       # 1× ATR 止損帶
            "stop_15x": float,      # 1.5× ATR 止損帶
            "stop_2x": float,       # 2× ATR 止損帶
            "series": list[dict],   # ATR 歷史序列（date/atr），供畫圖
            "error": str | None,
        }
    """
    try:
        df = fm.stock_price(sid, days=max(days, period * 3))
    except Exception as e:
        return {"error": str(e)}

    if df is None or df.empty:
        return {"error": "查無價格資料"}

    df = df.sort_values("date").copy()

    # FinMind 欄位：open / max / min / close / Trading_Volume
    rename = {"max": "high", "min": "low"}
    df = df.rename(columns=rename)

    required = {"high", "low", "close"}
    if not required.issubset(df.columns):
        return {"error": f"缺少欄位：{required - set(df.columns)}"}

    df[["high", "low", "close"]] = df[["high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["high", "low", "close"])

    if len(df) < period + 1:
        return {"error": f"歷史資料不足（需 >{period + 1} 筆，現有 {len(df)} 筆）"}

    # True Range
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
            abs(r["low"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
        ),
        axis=1,
    )

    # Wilder's RMA（與 TradingView 一致）
    atr_vals = [None] * len(df)
    tr = df["tr"].tolist()
    # 初始值：前 period 筆 TR 的 SMA
    first_atr = sum(tr[1 : period + 1]) / period
    atr_vals[period] = first_atr
    for i in range(period + 1, len(df)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period
    df["atr"] = atr_vals

    df_valid = df.dropna(subset=["atr"])
    if df_valid.empty:
        return {"error": "ATR 計算失敗"}

    latest = df_valid.iloc[-1]
    atr = round(float(latest["atr"]), 2)
    close = round(float(latest["close"]), 2)

    series = [
        {"date": str(r["date"])[:10], "atr": round(float(r["atr"]), 2)}
        for _, r in df_valid.tail(30).iterrows()
    ]

    return {
        "atr": atr,
        "close": close,
        "date": str(latest["date"])[:10],
        "stop_1x": round(close - atr, 2),
        "stop_15x": round(close - atr * 1.5, 2),
        "stop_2x": round(close - atr * 2, 2),
        "series": series,
        "error": None,
    }
