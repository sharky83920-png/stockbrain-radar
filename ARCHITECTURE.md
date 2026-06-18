# stockbrain 完整架構設計文檔

## 系統概覽

**目標：** 一個全自動的投顧報告聚合系統，整合國際分析、台灣本地報告、用戶上傳的 PDF，統一存檔、搜索、分析。

---

## 🏗️ 四層架構

### 層級 1：數據來源層（Sources）

#### 1.1 用戶上傳（已完成 ✅）
```
Google Drive/stockbrain/
├── 待閱讀區/          ← 用戶放 PDF
├── 閱讀完畢區/        ← 已處理的 PDF
└── 知識庫/            ← 輸出 Markdown
```
- **方式：** Google Drive 本機同步文件夾
- **觸發：** 手動掃描或定時監控
- **成本：** $0（Google Drive 免費）

#### 1.2 國際 API（Finnhub + NewsAPI）⏳ 待實現
```
Finnhub API
├── 獲取分析師評級
├── 12個月目標價
├── 買進/持有/賣出比例
└── 支持：TSMC (台積電 ADR)、MediaTek 等

NewsAPI
├── 金融新聞爬取
├── 關鍵詞搜索
└── 自動過濾台股相關
```
- **成本：** 免費層（60 requests/min），或 Finnhub Pro $9/月
- **更新频率：** 每天 2-3 次
- **數據格式：** JSON → 轉換成 Markdown

#### 1.3 Web Scraper（SeekingAlpha、台灣財經網）⏳ 待實現
```
SeekingAlpha
├── 爬取分析文章（免費版可公開訪問）
├── 作者評等和觀點
└── 存成 PDF 或 Markdown

台灣財經網站
├── 鉅亨網
├── 工商時報
├── 聯合新聞網（市場評論）
└── 自動轉成中文 Markdown
```
- **成本：** $0（公開網站）
- **難度：** 高（需 Selenium + IP 輪換）
- **更新频率：** 每天 1 次
- **風險：** ⚠️ 某些網站有反爬蟲機制

#### 1.4 高級數據源（可選未來擴展）
```
Bloomberg Terminal / FactSet
├── 機構級數據
├── 成本：$20k+/月
└── 需企業訂閱
```

---

### 層級 2：處理引擎層（Processing）

#### 2.1 PDF 處理器 ✅ 已完成
```python
class PDFToMarkdown:
    - extract_text_from_pdf()      # pdfplumber
    - extract_structured_data()    # 啟發式提取
    - generate_markdown()          # 模板生成
    - process_pdf()                # 完整流程
```

**當前功能：**
- ✅ 文本提取（前 8 頁）
- ✅ 股票代碼偵測（正則表達式）
- ✅ 公司名稱識別（映射表 + Gemini 備用）
- ✅ 評等提取（「買進」、「增加持股」等）
- ⚠️ 價格提取（準確度 50%）
- ⚠️ EPS 和財務數據（準確度 30%）

**改進計劃：**
- 升級到 Claude/Gemini API（當有 API 額度時）
- 增加多語言支持（英文報告）

#### 2.2 API 聚合器 ⏳ 待實現
```python
class APIAggregator:
    def fetch_finnhub_ratings(code)        # 評級和目標價
    def fetch_news(company_name)           # 最新新聞
    def deduplicate_reports()              # 去除重複
    def normalize_ratings()                # 統一評等格式
    
    Output: {"code": "2618", "ratings": {...}, "news": [...]}
```

**關鍵邏輯：**
- Finnhub 輸出 JSON → 轉成 Markdown 格式
- NewsAPI 過濾台股相關（台灣、TWD、股票代碼等）
- 評等統一：買進、增加、中立、減持、賣出

#### 2.3 Web Scraper 引擎 ⏳ 待實現
```python
class WebScraper:
    def scrape_seekingalpha(ticker)        # SeekingAlpha
    def scrape_taiwannews(keyword)         # 台灣新聞
    def scrape_guruguruji(stock_code)      # 鉅亨網
    def convert_to_markdown(html)          # HTML → MD
    def download_pdf(url)                  # 另存為 PDF
    
    Output: Markdown 或 PDF 文件
```

**技術選擇：**
- **簡單網站（靜態 HTML）：** BeautifulSoup
- **動態網站（JavaScript）：** Selenium
- **容錯機制：** Retry + IP 輪換 + User-Agent 隨機

#### 2.4 數據豐富化（Data Enrichment）⏳ 待實現
```python
class DataEnricher:
    def unify_stock_code(input)            # 2618 / TWD00002618 → 2618
    def normalize_company_name(name)       # 台積電 / TSMC / 2330 → 台積電
    def standardize_rating(text)           # 「買」「增加」→ 「買進」
    def extract_metadata(report)           # 日期、作者、來源
    
    Output: 標準化的結構化數據
```

**映射表管理：**
```json
{
  "stocks": {
    "2618": "長榮航",
    "2330": "台積電",
    ...
  },
  "sources": {
    "Finnhub": "國際分析師",
    "SeekingAlpha": "海外投資者",
    "鉅亨網": "台灣專業評論",
    ...
  }
}
```

---

### 層級 3：存儲層（Storage）

#### 3.1 知識庫（本地 Markdown）✅ 已完成
```
G:\我的雲端硬碟\stockbrain\知識庫\個股\
├── 2618_長榮航\
│   ├── 投顧報告\
│   │   ├── 凱基_2026-06-17.md
│   │   ├── Finnhub_2026-06-17.md       ← 新增
│   │   ├── SeekingAlpha_2026-06-17.md  ← 新增
│   │   └── 鉅亨_2026-06-17.md          ← 新增
│   ├── 國際評級\
│   │   └── 分析師共識_2026-06-17.md     ← 新增
│   └── 新聞追蹤\
│       └── 最新消息_2026-06-17.md      ← 新增
├── 2330_台積電\
│   └── ...
└── ...
```

#### 3.2 結構化數據庫（JSON）⏳ 待實現
```
stockbrain/
├── data/
│   ├── reports.json          ← 所有報告元數據
│   ├── ratings.json          ← 分析師評級
│   ├── news.json             ← 新聞索引
│   ├── stocks_mapping.json   ← 股票代碼映射
│   └── processing_log.json   ← 處理記錄
└── cache/
    └── api_responses/        ← API 快取（防止重複請求）
```

**reports.json 結構：**
```json
{
  "reports": [
    {
      "id": "2618-20260617-finviz",
      "code": "2618",
      "company": "長榮航",
      "source": "Finnhub",
      "type": "分析師評級",
      "date": "2026-06-17",
      "data": {
        "target_price": 48.0,
        "current_price": 39.75,
        "upside": "20.8%",
        "ratings": {
          "buy": 5,
          "hold": 3,
          "sell": 1
        }
      },
      "markdown_path": "知識庫/個股/2618_長榮航/國際評級/...",
      "processed_at": "2026-06-17T12:30:45Z"
    },
    ...
  ],
  "meta": {
    "last_updated": "2026-06-17T12:30:45Z",
    "total_reports": 1245,
    "total_stocks": 157
  }
}
```

#### 3.3 搜索索引 ⏳ 待實現
```python
class SearchIndex:
    def build_index()                     # 從 reports.json 構建
    def search_by_code(code)              # 2618
    def search_by_company(name)           # 長榮航 / 航空
    def search_by_source(source)          # Finnhub / SeekingAlpha
    def search_by_date_range(start, end)  # 日期範圍
    def search_by_keyword(keyword)        # 全文搜索
```

---

### 層級 4：用戶界面層（UI）

#### 4.1 Streamlit 儀表盤 ⏳ 待實現

**頁面結構：**

```
📊 Main Dashboard
├── 📈 統計面板
│   ├── 最近 30 天新增報告數
│   ├── 按來源分佈（Finnhub vs SeekingAlpha vs 鉅亨 vs 用戶上傳）
│   └── 按股票分佈（前 10 大）
│
├── 🔍 搜索面板
│   ├── 股票代碼搜索 (2618)
│   ├── 公司名稱搜索 (長榮航)
│   ├── 關鍵詞全文搜索
│   └── 日期範圍篩選
│
├── 📰 報告瀏覽
│   ├── 顯示 Markdown 內容
│   ├── 評等視覺化（餅圖）
│   ├── 價格趨勢圖
│   └── 下載 PDF / Markdown
│
└── ⏱️ 任務管理
    ├── API 同步狀態
    ├── Web Scraper 運行日誌
    ├── 定時任務設定
    └── 手動觸發按鈕
```

**核心功能：**
```python
# 頁面代碼結構
pages/
├── 00_📊_Dashboard.py           # 首頁統計
├── 01_🔍_Search.py              # 搜索
├── 02_📈_Stock_Analysis.py      # 單隻股票分析
├── 03_📰_Reports.py             # 報告瀏覽
└── 04_⚙️_Settings.py            # 設定和任務管理
```

---

## 📋 數據流示例

### 案例 1：用戶上傳 PDF
```
用戶丟 PDF → Google Drive/待閱讀區
       ↓
系統檢測（手動掃描或定時）
       ↓
PDFToMarkdown 處理
  ├─ 提取文本
  ├─ 檢測股票代碼（2618）
  ├─ 識別公司名稱（長榮航）
  └─ 生成 Markdown
       ↓
KnowledgeBaseManager 存檔
  └─ 知識庫/個股/2618_長榮航/投顧報告/
       ↓
reports.json 更新
       ↓
搜索索引重建
       ↓
儀表盤展示（自動刷新）
```

### 案例 2：自動從 Finnhub 獲取評級
```
定時任務觸發（每天 8:00）
       ↓
APIAggregator.fetch_finnhub_ratings("2618")
       ↓
獲得 JSON：
{
  "buy": 5,
  "hold": 3,
  "sell": 1,
  "target_price": 48.00
}
       ↓
DataEnricher 標準化
       ↓
生成 Markdown：
"# 台積電 (2330) 國際分析師共識
| 評等 | 數量 |
| 買進 | 15 |
..."
       ↓
存到知識庫/個股/2618_長榮航/國際評級/
       ↓
reports.json 記錄：
{
  "id": "2618-20260617-finnhub",
  "source": "Finnhub",
  "data": {...}
}
       ↓
搜索索引更新
       ↓
儀表盤展示
```

### 案例 3：自動爬取 SeekingAlpha
```
定時任務觸發（每天 10:00）
       ↓
WebScraper.scrape_seekingalpha("2618")
       ↓
Selenium 打開頁面 → BeautifulSoup 解析
       ↓
提取：
- 文章標題
- 作者評分
- 發布日期
- 內容摘要
       ↓
生成 Markdown
       ↓
（可選）下載 PDF
       ↓
存到知識庫/個股/2618_長榮航/投顧報告/
       ↓
標記來源為 "SeekingAlpha"
       ↓
記錄到 reports.json
```

---

## 🔧 技術堆棧

| 層級 | 組件 | 技術 | 狀態 |
|------|------|------|------|
| **數據來源** | PDF 讀取 | pdfplumber | ✅ 完成 |
| | Google Drive 同步 | 本機文件夾 | ✅ 完成 |
| | Finnhub API | requests + json | ⏳ 待做 |
| | NewsAPI | requests + json | ⏳ 待做 |
| | Web Scraping | Selenium + BeautifulSoup | ⏳ 待做 |
| **處理** | PDF 轉 Markdown | 自定義（啟發式） | ✅ 完成 |
| | 數據標準化 | 自定義 + 正則 | ⚠️ 部分 |
| | API 聚合 | 自定義 | ⏳ 待做 |
| **存儲** | 知識庫 | 本地 Markdown | ✅ 完成 |
| | JSON 數據庫 | 文件系統 | ⏳ 待做 |
| | 搜索索引 | jieba (中文) | ⏳ 待做 |
| **UI** | 儀表盤 | Streamlit | ⏳ 待做 |

---

## 📁 目錄結構（完整版）

```
C:\Users\User\projects\stockbrain-radar\
├── src/
│   ├── utils/
│   │   ├── pdf_to_md.py                    ✅ 已有
│   │   ├── google_drive_monitor.py         ✅ 已有
│   │   ├── report_processor.py             ✅ 已有
│   │   ├── report_monitor.py               ✅ 已有
│   │   ├── knowledge_base_manager.py       ✅ 已有
│   │   ├── api_aggregator.py               ⏳ 新建
│   │   ├── web_scraper.py                  ⏳ 新建
│   │   ├── data_enricher.py                ⏳ 新建
│   │   ├── search_index.py                 ⏳ 新建
│   │   └── cache_manager.py                ⏳ 新建
│   │
│   └── app/
│       ├── dashboard.py                    ✅ 已有（基礎版）
│       └── pages/
│           ├── 00_Dashboard.py             ⏳ 新建
│           ├── 01_Search.py                ⏳ 新建
│           ├── 02_Stock_Analysis.py        ⏳ 新建
│           └── 03_Settings.py              ⏳ 新建
│
├── data/
│   ├── reports.json                        ⏳ 新建
│   ├── ratings.json                        ⏳ 新建
│   ├── stocks_mapping.json                 ⏳ 新建
│   └── cache/                              ⏳ 新建
│
├── config/
│   ├── api_keys.env                        ✅ 已有
│   ├── sources_config.json                 ⏳ 新建
│   └── scheduler_config.json               ⏳ 新建
│
├── logs/
│   ├── api_sync.log                        ⏳ 新建
│   ├── web_scraper.log                     ⏳ 新建
│   └── errors.log                          ⏳ 新建
│
└── README.md, ARCHITECTURE.md, ...
```

---

## 📅 實施時間表（建議）

### Phase 1: API 集成（1-2 天）
- [ ] Finnhub API 集成
- [ ] NewsAPI 集成
- [ ] 數據轉換為 Markdown
- [ ] 定時任務框架

### Phase 2: Web Scraper（2-3 天）
- [ ] SeekingAlpha Scraper
- [ ] 台灣財經網 Scraper
- [ ] 錯誤處理 + 重試機制
- [ ] PDF 下載邏輯

### Phase 3: 數據管理（1-2 天）
- [ ] JSON 數據庫結構
- [ ] 搜索索引建立
- [ ] 去重複邏輯
- [ ] 快取管理

### Phase 4: UI 升級（2-3 天）
- [ ] Streamlit 多頁應用
- [ ] 搜索和過濾界面
- [ ] 統計視覺化
- [ ] 任務管理面板

**總時間估計：** 6-10 天（全職開發）

---

## ⚠️ 風險和注意事項

### 1. Web Scraping 法律風險
- **風險：** 某些網站的 ToS 禁止爬蟲
- **解決：** 
  - ✅ 使用 API（Finnhub、NewsAPI）→ 合法
  - ⚠️ 爬公開網站 → 需檢查 robots.txt 和 ToS
  - ❌ 繞過付費牆 → 違法

### 2. API 配額和成本
- **Finnhub Free：** 60 requests/min （足夠）
- **NewsAPI Free：** 100 requests/day （足夠）
- **成本升級：** Finnhub Pro $9/月 = 無限制

### 3. 性能和存儲
- **預計數據量：** 1 股票 × 10 報告/月 × 12 月 = 120 MB（JSON）
- **搜索延遲：** 1000 份報告 = <100ms （jieba 索引）
- **更新频率：** 每天 3 次同步 = 足夠

### 4. 數據質量
- **API 數據：** 結構化，準確度 95%
- **爬蟲數據：** 非結構化，需數據清洗
- **用戶 PDF：** 格式多樣，需啟發式提取

---

## 🎯 關鍵設計決策

### 決策 1：本地 JSON vs 數據庫
- **選擇：** 本地 JSON
- **理由：** 
  - 簡單，無需 DB 服務
  - 易於備份（Google Drive）
  - 查詢速度足夠（<10k 報告）

### 決策 2：實時同步 vs 定時批量
- **選擇：** 定時批量（每天 3 次）
- **理由：**
  - 降低 API 成本
  - 避免頻繁 I/O
  - 足夠滿足用戶需求

### 決策 3：Streamlit vs 自建 Web
- **選擇：** Streamlit
- **理由：**
  - 快速開發（1-2 天 vs 1 週）
  - Python 生態完整
  - 適合數據驅動的應用

### 決策 4：Selenium vs API-only
- **選擇：** 混合方案
  - API first（Finnhub / NewsAPI）
  - 爬蟲 second（SeekingAlpha / 台灣網站）
- **理由：**
  - API 更穩定可靠
  - 爬蟲補充 API 缺口
  - 最大化數據覆蓋

---

## ✅ 架構驗證清單

- [ ] 所有層級（源→處理→存儲→UI）已規劃
- [ ] 數據流（3 個案例）已驗證
- [ ] 技術堆棧無衝突
- [ ] 時間估計合理（6-10 天）
- [ ] 成本可控（$0-50/月）
- [ ] 風險已列舉和解決
- [ ] 每個模塊有清晰的輸入/輸出

---

**準備好開始實施了嗎？** 

→ 下一步：選擇 Phase 1 開始開發
