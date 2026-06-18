# 投顧報告自動化系統

簡潔清爽的投顧報告讀取、分析、歸檔系統。

---

## 📋 系統架構

```
Google Drive (stockbrain)
├─ 待閱讀區/          ← 你丟 PDF 在這
├─ 知識庫/            ← 自動生成的 md 在這
│  └─ 個股/
│     ├─ 2317_鴻海/投顧報告/凱基_2026-05-26.md
│     ├─ 2324_仁寶/投顧報告/凱基_2026-06-17.md
│     └─ ...
├─ 閱讀完畢區/        ← 已讀的 PDF 自動移到這
└─ .processing_config.json  ← 記錄處理狀態（防重複）
```

---

## 🚀 使用方式

### 方式 A：手動掃描（在任何對話窗）

**在這個 Claude Code 對話窗說：**
```
處理待閱讀區
或
掃描報告
或
開始掃描
```

**系統會立即：**
1. 掃描 Google Drive/stockbrain/待閱讀區/
2. 讀取所有新 PDF
3. Claude 智能摘要
4. 生成 md 文件 → 存到知識庫
5. 移動 PDF → 閱讀完畢區/
6. 顯示結果

---

### 方式 B：自動監控（後台運行）

**在終端執行：**
```bash
cd C:\Users\User\projects\stockbrain-radar
.venv\Scripts\Activate.ps1
python -c "from src.utils.report_monitor import start_monitor; start_monitor(interval=300)"
```

**系統會：**
1. 每 5 分鐘自動掃描一次
2. 有新 PDF → 自動處理
3. 24/7 運行（除非手動停止）
4. 無需手動干預

---

## 📝 Markdown 文件格式

自動生成的 md 包含：
```markdown
# 鴻海 (2317) - 投顧報告

**報告日期：** 2026-05-26
**檔案名：** document.pdf

---

## 投資要點

| 項目 | 數值 |
|------|------|
| **現價** | 259.0 元 |
| **目標價** | 315.0 元 |
| **上漲空間** | 21.6% |
| **評等** | 增加持股 |

---

## 財務預估

| 年度 | EPS |
|------|------|
| **2026F** | 17.94 元 |
| **2027F** | 21.46 元 |

---

## 核心邏輯

**投資邏輯：**
[Claude 提取的邏輯]

**成長動能：**
[Claude 提取的動能]

**主要風險：**
[Claude 提取的風險]
```

---

## 🔄 工作流程

### 新 PDF 到達
```
你丟 PDF 到待閱讀區
  ↓
系統檢測（自動或手動掃描）
  ├─ 檢查是否已處理（用 config.json）
  ├─ 如果已處理 → 跳過
  ├─ 如果新的 → 繼續
  ↓
pdfplumber 讀取 PDF 文本（前 3 頁）
  ↓
Claude Opus 分析報告
  ├─ 提取股票代碼、公司名、目標價
  ├─ 提取投資邏輯、成長動能、風險
  ├─ 生成結構化數據
  ↓
生成 Markdown 文件
  ↓
存到知識庫（按股票代碼分類）
  ├─ 路徑：知識庫/個股/2317_鴻海/投顧報告/凱基_2026-05-26.md
  ↓
移動原 PDF 到閱讀完畢區
  ↓
更新 config.json（記錄已處理）
  ↓
✅ 完成！
```

---

## 📊 配置文件格式

`.processing_config.json`：
```json
{
  "last_scan": "2026-06-17T12:30:45",
  "processed_pdfs": [
    "document (5).pdf",
    "凱基_鴻海_20260526.pdf"
  ],
  "stats": {
    "total": 2,
    "success": 2,
    "failed": 0
  }
}
```

---

## ✅ 特點

- ✅ **持久化**：不依賴對話窗狀態
- ✅ **跨電腦**：數據在 Google Drive
- ✅ **自動化**：可後台 24/7 運行
- ✅ **防重複**：配置文件追蹤已處理
- ✅ **智能摘要**：Claude Opus 分析
- ✅ **自動分類**：按股票代碼歸檔
- ✅ **靈活觸發**：手動掃描 + 自動監控

---

## 📦 依賴

```
anthropic>=0.9.0      （Claude API）
pdfplumber            （PDF 讀取）
```

安裝：
```bash
pip install anthropic pdfplumber
```

---

## ⚙️ 環境設定

**必需：**
- `ANTHROPIC_API_KEY` 在 `.env`

**Google Drive：**
- 使用 Windows 同步文件夾（G:/我的雲端硬碟）
- 無需額外設定 Google Drive API

---

## 🔧 進階用法

### 在 Python 中調用

```python
# 手動掃描
from src.utils.report_monitor import manual_scan
result = manual_scan()
print(result)

# 啟動自動監控
from src.utils.report_monitor import start_monitor
start_monitor(interval=300)  # 每 5 分鐘掃描

# 訪問原始數據
from src.utils.report_processor import ReportProcessor
processor = ReportProcessor()
result = processor.process_all_pending()
print(result)
```

---

## 📝 常見問題

### Q: 如何停止自動監控？
A: 按 `Ctrl+C` 即可停止。

### Q: 系統會重複處理同一份 PDF 嗎？
A: 不會。`.processing_config.json` 記錄了已處理的 PDF，系統會跳過。

### Q: 可以自訂掃描間隔嗎？
A: 可以。`start_monitor(interval=600)` 改為 10 分鐘。

### Q: 生成的 md 位置在哪？
A: Google Drive/stockbrain/知識庫/個股/[代碼]_[公司]/投顧報告/

### Q: 如何查看處理統計？
A: 查看 `.processing_config.json` 的 `stats` 字段。

---

## 🎯 下一步

1. ✅ 系統架構完成
2. ⏳ 手動掃描功能 → 在對話窗測試
3. ⏳ 自動監控功能 → 後台運行測試
4. ⏳ 驗證 md 生成和分類

---

*系統設計簡潔清爽，可靠可信！*
