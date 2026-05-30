# StockBrain Radar

個人版台股研究分析工具。輸入股票代號 → 自動拉齊 SOP 要看的資料（三大法人、籌碼、月營收、EPS、財報、估值）→ 依研究 SOP 排版 + 紅綠燈評分。

資料來源：FinMind API（免費）+ 證交所開放資料。介面：Streamlit。

## 快速開始

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 設定 FinMind token（可選，無 token 為低速匿名模式）
copy .env.example .env          # 然後編輯填入 FINMIND_TOKEN

# 連通測試
python scripts/test_connection.py

# 啟動 dashboard（Phase 2 之後）
streamlit run src/app/dashboard.py
```

## 路線圖

- [x] Phase 0：環境 + FinMind 連通
- [ ] Phase 1：資料層（FinMind client + SQLite 快取）
- [ ] Phase 2：Streamlit 個股研究 dashboard MVP
- [ ] Phase 3：SOP 自動評分 + 紅綠燈
- [ ] Phase 4：觀察名單 / 持股 / 跨股比較
- [ ] Phase 5：投顧報告抓取
- [ ] Phase 6：每日雷達 + LINE 推播
