"""回補 00878 歷史持股到 vault，並印出最近一次的加減碼變化。

跑法（在 stockbrain-radar 資料夾，需連網）：
    .venv/Scripts/python scripts/etf_backfill.py                 # 預設 2023-01-01 至今
    .venv/Scripts/python scripts/etf_backfill.py 2026-01-01      # 指定起日
    .venv/Scripts/python scripts/etf_backfill.py 2026-01-01 2026-06-30
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from src.data import etf_holdings as eh  # noqa: E402

FUND = "00878"
start = sys.argv[1] if len(sys.argv) > 1 else "2023-01-01"
end = sys.argv[2] if len(sys.argv) > 2 else None

print(f"=== 回補 {FUND} 持股 {start} ~ {end or '今天'} ===")
eh.backfill(FUND, start=start, end=end)

dates = eh.stored_dates(FUND)
if len(dates) >= 2:
    d, prev = dates[-1], dates[-2]
    print(f"\n=== 最新變化：{prev} → {d} ===")
    chg = eh.share_changes(FUND, d, prev)
    moved = chg[chg["event"] != "不變"]
    if moved.empty:
        print("（這兩日之間股數無變化）")
    else:
        for r in moved.head(15).itertuples(index=False):
            pct = f"{r.pct:+.1f}%" if r.pct is not None else "—"
            print(f"  {r.event}  {r.stock_code:<6} {r.stock_name:<8} "
                  f"股數 {r.prev_shares:>14,} → {r.shares:>14,}  ({pct})")
