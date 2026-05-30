"""Phase 0 連通測試：抓台積電(2330)資料，確認 FinMind 通了。"""
import sys
from pathlib import Path

# Windows 終端機預設 cp950，中文/emoji 會壞，強制 UTF-8 輸出
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import finmind_client as fm


def main() -> None:
    print("=== FinMind 連通測試 (2330 台積電) ===")
    has_token = bool(fm._token())
    print(f"Token: {'有' if has_token else '無（匿名低速模式）'}\n")

    price = fm.stock_price("2330", days=10)
    if price.empty:
        print("⚠️ 沒抓到股價資料，可能是匿名速率被限制，註冊 token 後再試。")
        return

    latest = price.iloc[-1]
    print(f"最新交易日: {latest['date']}")
    print(f"收盤價: {latest['close']}  漲跌: {latest.get('spread', 'n/a')}")
    print(f"成交量(股): {latest['Trading_Volume']:,}")
    print(f"\n抓到 {len(price)} 筆日 K，連通成功 ✅")


if __name__ == "__main__":
    main()
