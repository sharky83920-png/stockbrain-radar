"""診斷 + 驗證 集保股權分散（大戶持股分級）。

用途：你之前 TaiwanStockHoldingSharesPer 回 400，這支幫忙確認：
1. 到底能不能拿到資料（沒 token / 要 token？）
2. 真實欄位名稱與「持股分級」字串長怎樣（決定怎麼算大戶持股比）

跑法（在 stockbrain-radar 資料夾，需連網）：
    .venv/Scripts/python scripts/probe_holding.py 2317
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from src.data import finmind_client as fm  # noqa: E402

sid = sys.argv[1] if len(sys.argv) > 1 else "2317"
print(f"=== 探測 {sid} 集保股權分散 (TaiwanStockHoldingSharesPer) ===")
try:
    df = fm.holding_distribution(sid, weeks=16)
except Exception as e:  # noqa: BLE001
    print(f"❌ 失敗：{type(e).__name__}: {e}")
    print("→ 若是 402/權限：此資料集可能需要 FinMind token，請確認 .env 的 FINMIND_TOKEN 已填。")
    sys.exit(1)

if df.empty:
    print("⚠️ 回傳空（可能此檔無資料、或需要 token）。")
    sys.exit(0)

print("\n欄位：", list(df.columns))
print("資料筆數：", len(df))
dates = sorted(df["date"].unique()) if "date" in df.columns else []
print("週次：", dates[:3], "...", dates[-3:] if len(dates) > 3 else "")

# 列出最新一週的所有分級，方便確認「大戶」門檻怎麼抓
level_col = next((c for c in df.columns if "Level" in c or "level" in c or "級距" in c), None)
pct_col = next((c for c in df.columns if "percent" in c.lower() or "比例" in c), None)
print("\n推測 分級欄=", level_col, " 百分比欄=", pct_col)
if level_col and dates:
    latest = df[df["date"] == dates[-1]]
    print(f"\n--- 最新一週 {dates[-1]} 各分級 ---")
    for _, r in latest.iterrows():
        print(f"  {r[level_col]!s:>22} | {pct_col}={r.get(pct_col)}")
