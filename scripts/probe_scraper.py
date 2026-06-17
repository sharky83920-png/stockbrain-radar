"""探針：找出「買賣家數差 / 主力買賣超」哪個免費網站在你電腦上抓得到。

它會試打幾個候選網站，回報：
- HTTP 狀態碼（200 才有戲；403/封鎖則跳過）
- 內容長度
- 原始 HTML 裡有沒有關鍵字（有 → 伺服器直接吐資料、可解析；沒有 → 多半是 JS 動態載入、純爬蟲抓不到）

跑法（在 stockbrain-radar 資料夾，需連網）：
    .venv/Scripts/python scripts/probe_scraper.py 2317

把整段輸出貼回給 Claude，他就能挑出可用來源、寫對應的解析器。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from src.data import chip_scraper as cs  # noqa: E402

sid = sys.argv[1] if len(sys.argv) > 1 else "2317"

SOURCES = {
    "Goodinfo-法人/籌碼": f"https://goodinfo.tw/tw/ShowBuySaleChart.asp?STOCK_ID={sid}&CHT_CAT=DATE",
    "HiStock-主力進出": f"https://histock.tw/stock/main.aspx?no={sid}",
    "HiStock-集中度": f"https://histock.tw/stock/large.aspx?no={sid}",
    "HiStock-分點日報": f"https://histock.tw/stock/branch.aspx?no={sid}",
    "WantGoo-主力動向": f"https://www.wantgoo.com/stock/{sid}/major-investors/main-trend",
}
KEYS = ["買賣家數差", "主力", "集中度", "買超", "賣超", "家數"]

print(f"=== 探測 {sid} 籌碼來源（買賣家數差/主力）===\n")
for name, url in SOURCES.items():
    try:
        r = cs.get(url)
        text = r.text or ""
        hits = [k for k in KEYS if k in text]
        verdict = "✅ 原始HTML含關鍵字(可解析)" if len(hits) >= 2 else "⚠️ 關鍵字少(可能JS動態載入)"
        if r.status_code != 200:
            verdict = "❌ 非200，可能被擋"
        print(f"[{name}]")
        print(f"  狀態={r.status_code}  長度={len(text)}  命中關鍵字={hits}")
        print(f"  判定：{verdict}")
        print(f"  url={url}\n")
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] ❌ 連線失敗：{type(e).__name__}: {e}\n  url={url}\n")

print("→ 把上面整段貼回給 Claude，他會挑可用來源、寫解析器。")
