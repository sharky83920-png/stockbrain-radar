"""探測 FinMind 各 dataset 對 2330 的真實欄位與樣貌，供 Phase 1 設計聚合層。"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import finmind_client as fm

SID = "2330"

DATASETS = [
    ("TaiwanStockPrice", 10),
    ("TaiwanStockInstitutionalInvestorsBuySell", 10),
    ("TaiwanStockMarginPurchaseShortSale", 10),
    ("TaiwanStockMonthRevenue", 400),
    ("TaiwanStockPER", 10),
    ("TaiwanStockFinancialStatements", 400),
    ("TaiwanStockBalanceSheet", 400),
    ("TaiwanStockShareholding", 60),
    ("TaiwanStockHoldingSharesPer", 60),
]


def probe(dataset: str, days: int) -> None:
    print(f"\n{'='*60}\n{dataset}")
    try:
        df = fm.fetch(dataset, SID, fm._default_start(days))
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {type(e).__name__}: {e}")
        return
    if df.empty:
        print("  (空 — 此資料集無資料或被限速)")
        return
    print(f"  rows={len(df)}  cols={list(df.columns)}")
    if "type" in df.columns:
        print(f"  type 種類: {sorted(df['type'].unique())}")
    print("  最後 1 列:")
    print("   ", df.iloc[-1].to_dict())


if __name__ == "__main__":
    for ds, d in DATASETS:
        probe(ds, d)
