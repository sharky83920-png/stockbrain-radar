"""探測股利 / 新聞 / 長天期股價+EPS（給河流圖用）。"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import finmind_client as fm

SID = "2330"


def probe(dataset, days, **kw):
    print(f"\n{'='*60}\n{dataset}  (days={days})")
    try:
        df = fm.fetch(dataset, SID, fm._default_start(days), **kw)
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {type(e).__name__}: {e}")
        return None
    if df.empty:
        print("  (空)")
        return df
    print(f"  rows={len(df)}  cols={list(df.columns)}")
    if "type" in df.columns:
        print(f"  type: {sorted(df['type'].unique())}")
    print("  最後 2 列:")
    for _, r in df.tail(2).iterrows():
        print("   ", r.to_dict())
    return df


if __name__ == "__main__":
    probe("TaiwanStockDividend", 1500)
    probe("TaiwanStockNews", 14)
    # 長天期股價（河流圖）
    p = probe("TaiwanStockPrice", 1100)
    if p is not None and not p.empty:
        print(f"\n股價最早: {p['date'].min()}  最新: {p['date'].max()}  共 {len(p)} 筆")
