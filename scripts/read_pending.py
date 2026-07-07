"""
統一待閱讀區處理器

掃描 待閱讀區/*.pdf，自動判斷類型。
掃描檔（無文字層的圖片型 PDF）會自動改用 Gemini 多模態 OCR 轉錄後照常處理。
  - 投資家日報  → Gemini 萃取 → 知識庫/個股/{sid}/投資家日報/*.md
  - 投顧報告    → Gemini 萃取 → 知識庫/個股/{sid}/投顧報告/*.md
  - 書籍掃描    → Gemini 讀書筆記 → 知識庫/書籍筆記/{書名}/*.md
  - 無法判斷    → 知識庫/個股/_未分類/*.md（不移動，提示人工確認）

原始 PDF 統一移至：原始資料庫（原始格式）/{類型}/
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

from src.data import gemini_client as gem

VAULT       = Path(os.getenv("RADAR_VAULT_DIR", r"G:\我的雲端硬碟\stockbrain"))
PENDING_DIR = VAULT / "待閱讀區"
KB_DIR      = VAULT / "知識庫" / "個股"
ARCHIVE_DIR = VAULT / "原始資料庫（原始格式）"

# ── 類型識別關鍵字 ─────────────────────────────────────────────────────────
DAILY_MARKERS   = ["投資家日報", "孫慶龍", "投資家觀點", "InvestorDaily"]
BROKER_MARKERS  = ["凱基", "元大證券", "富邦證券", "國泰證券", "群益證券",
                   "中信證券", "永豐金證券", "兆豐證券", "第一金證券",
                   "目標價", "投資評等", "Buy", "Outperform", "Neutral",
                   "12個月目標", "12-Month Target"]
# 書籍掃描：有「第X篇/章」章節結構或 ISBN（日報與投顧報告不會有）
BOOK_PAT = re.compile(r"第\s*[0-9一二三四五六七八九十百]+\s*[篇章]")


def _read_text(pdf: Path, max_pages: int = 8) -> str:
    try:
        with pdfplumber.open(str(pdf)) as f:
            return "\n".join(
                p.extract_text() or "" for p in f.pages[:max_pages]
            )
    except Exception as e:
        print(f"  ⚠️  讀取失敗：{e}")
        return ""


_OCR_PROMPT = """以上是一份掃描文件（圖片型，沒有文字層），最多取前 {max_pages} 頁。
請將其中的文字完整轉錄為純文字，依原始閱讀順序輸出，
保留所有數字、日期、股票代號與表格內容（表格用文字排版即可）。
不要翻譯、不要摘要、不要加任何說明或註解。"""


def _ocr_text(pdf: Path, max_pages: int = 8) -> str:
    """掃描檔備援：PDF 丟給 Gemini 多模態直接 OCR。"""
    if not gem.is_configured():
        print("  ⚠️  掃描檔需要 Gemini OCR，但未設定 GEMINI_KEY。")
        return ""
    print(f"  🔎 無文字層（掃描檔），改用 Gemini OCR（前 {max_pages} 頁）...")
    try:
        return gem.generate_with_pdf(_OCR_PROMPT.format(max_pages=max_pages),
                                     pdf, max_pages=max_pages)
    except Exception as e:
        print(f"  ⚠️  Gemini OCR 失敗：{e}")
        return ""


def _detect(pdf: Path, text: str) -> str:
    """回傳 'daily' / 'broker' / 'book' / 'unknown'"""
    name = pdf.name
    head = text[:800]
    # 明確的日報字樣優先（書裡也可能出現作者名，但不會自稱投資家日報）
    if any(m in name or m in head for m in ("投資家日報", "投資家觀點", "InvestorDaily")):
        return "daily"
    if BOOK_PAT.search(text[:3000]) or "ISBN" in text[:3000]:
        return "book"
    if any(m in name or m in head for m in DAILY_MARKERS):
        return "daily"
    if any(m in name or m in head for m in BROKER_MARKERS):
        return "broker"
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════
# 投資家日報處理
# ══════════════════════════════════════════════════════════════════════════
_DAILY_PROMPT = """你是台股投資研究助理。以下是《投資家日報》（孫慶龍）一份日報全文，請依指定格式萃取。

【全文】
{text}

【輸出：只回傳 JSON，不要其他文字】
{{
  "date": "YYYY-MM-DD",
  "stocks": [{{"sid": "4位代號", "name": "公司中文名"}}],
  "theme": "本期主題（15字內）",
  "industry": "產業（如 AI測試/半導體）",
  "core_thesis": "核心投資邏輯（2~4句）",
  "key_points": ["重點1", "重點2", "重點3"],
  "key_data": ["數據1", "數據2"],
  "risk": "主要風險（1~2句或null）",
  "outlook": "展望結論（1~2句）"
}}"""


def _process_daily(pdf: Path, text: str) -> dict | None:
    info = None
    if gem.is_configured():
        try:
            raw = gem.generate(_DAILY_PROMPT.format(text=text[:6000]))
            raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw.strip())
            info = json.loads(raw)
        except Exception as e:
            print(f"  ⚠️  Gemini 萃取失敗：{e}")

    if not info:
        date_m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
        date = (f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
                if date_m else datetime.now().strftime("%Y-%m-%d"))
        sids = [{"sid": s, "name": ""} for s in dict.fromkeys(re.findall(r"\((\d{4})\)", text))[:3]]
        info = {"date": date, "stocks": sids, "theme": pdf.stem[:20],
                "industry": "", "core_thesis": text[200:500].replace("\n", " "),
                "key_points": [], "key_data": [], "risk": None, "outlook": ""}

    stocks = info.get("stocks") or [{"sid": "_未分類", "name": ""}]
    date_str = info.get("date", datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    theme_slug = re.sub(r"[^\w一-鿿]", "", info.get("theme", ""))[:20]
    stocks_str = "、".join(f"{s.get('name','')}({s['sid']})" for s in stocks)
    tags = ["投資家日報"] + [s["sid"] for s in stocks]
    kp = "\n".join(f"- {p}" for p in info.get("key_points", []))
    kd = "\n".join(f"- {d}" for d in info.get("key_data", []))

    md = f"""---
date: {info["date"]}
source: 投資家日報（孫慶龍）
stocks: {stocks_str}
theme: {info.get("theme", "")}
industry: {info.get("industry", "")}
tags: [{", ".join(tags)}]
original_file: {pdf.name}
---

# {info["date"]}｜{info.get("theme", "")}

> **標的**：{stocks_str}　｜　**產業**：{info.get("industry", "")}

## 核心論點
{info.get("core_thesis", "")}

## 重點摘要
{kp or "（見原文）"}

## 關鍵數據
{kd or "（見原文）"}

## 展望
{info.get("outlook", "")}

## 風險
{info.get("risk") or "（本期未明確提及）"}

---
*來源：投資家日報 {info["date"]}　整理：{datetime.now().strftime("%Y-%m-%d")}*
"""
    sid  = stocks[0]["sid"]
    name = stocks[0].get("name", "")
    out_dir = KB_DIR / (f"{sid}_{name}" if name else sid) / "投資家日報"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date_str}_{theme_slug}.md").write_text(md, encoding="utf-8")
    print(f"  ✅ [日報] → {out_dir.relative_to(VAULT)}/{date_str}_{theme_slug}.md")

    dest = ARCHIVE_DIR / "投資家日報" / pdf.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf), str(dest))
    print(f"  📦 PDF → {dest.relative_to(VAULT)}")
    return info


# ══════════════════════════════════════════════════════════════════════════
# 投顧報告處理
# ══════════════════════════════════════════════════════════════════════════
_BROKER_PROMPT = """你是台股投資研究助理。以下是一份投顧研究報告，請依指定格式萃取。

【全文（前段）】
{text}

【輸出：只回傳 JSON，不要其他文字】
{{
  "date": "YYYY-MM-DD",
  "broker": "券商名稱（如凱基/元大/富邦）",
  "sid": "4位股票代號",
  "name": "公司中文名",
  "rating": "投資評等（買進/持有/中立/賣出/增持/減持）",
  "target_price": 目標股價數字或null,
  "current_price": 現價數字或null,
  "eps_this_year": EPS預估（今年）數字或null,
  "eps_next_year": EPS預估（明年）數字或null,
  "core_view": "核心投資邏輯（2~3句）",
  "growth_driver": "成長動能（1~2句）",
  "risk": "主要風險（1~2句）"
}}"""


def _process_broker(pdf: Path, text: str) -> dict | None:
    info = None
    if gem.is_configured():
        try:
            raw = gem.generate(_BROKER_PROMPT.format(text=text[:5000]))
            raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw.strip())
            info = json.loads(raw)
        except Exception as e:
            print(f"  ⚠️  Gemini 萃取失敗：{e}")

    if not info:
        date_m = re.search(r"(\d{4})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})", text)
        date = (f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
                if date_m else datetime.now().strftime("%Y-%m-%d"))
        sid_m = re.search(r"\((\d{4})\)", text)
        info = {"date": date, "broker": "未知券商",
                "sid": sid_m.group(1) if sid_m else "_未分類",
                "name": "", "rating": "", "target_price": None,
                "current_price": None, "eps_this_year": None,
                "eps_next_year": None, "core_view": text[200:400].replace("\n", " "),
                "growth_driver": "", "risk": ""}

    sid    = info.get("sid") or "_未分類"
    name   = info.get("name") or ""
    broker = info.get("broker") or "投顧"
    date   = info.get("date") or datetime.now().strftime("%Y-%m-%d")
    date_str = date.replace("-", "")

    tp  = f"{info['target_price']} 元" if info.get("target_price") else "—"
    cp  = f"{info['current_price']} 元" if info.get("current_price") else "—"
    epy = f"{info['eps_this_year']} 元" if info.get("eps_this_year") else "—"
    epn = f"{info['eps_next_year']} 元" if info.get("eps_next_year") else "—"

    md = f"""---
date: {date}
source: {broker}
stocks: {name}({sid})
rating: {info.get("rating", "")}
target_price: {info.get("target_price")}
tags: [投顧報告, {broker}, {sid}]
original_file: {pdf.name}
---

# {date}｜{broker} — {name}({sid}) {info.get("rating", "")}

## 關鍵數字

| 項目 | 數值 |
|---|---|
| 投資評等 | {info.get("rating", "—")} |
| 目標股價 | {tp} |
| 現價（報告時） | {cp} |
| EPS 預估（今年） | {epy} |
| EPS 預估（明年） | {epn} |

## 核心觀點
{info.get("core_view", "")}

## 成長動能
{info.get("growth_driver", "")}

## 主要風險
{info.get("risk", "")}

---
*來源：{broker} {date}　整理：{datetime.now().strftime("%Y-%m-%d")}*
"""
    out_dir = KB_DIR / (f"{sid}_{name}" if name else sid) / "投顧報告"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{date_str}_{broker}.md"
    (out_dir / fname).write_text(md, encoding="utf-8")
    print(f"  ✅ [投顧] → {out_dir.relative_to(VAULT)}/{fname}")

    dest = ARCHIVE_DIR / "投顧報告" / pdf.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf), str(dest))
    print(f"  📦 PDF → {dest.relative_to(VAULT)}")
    return info


# ══════════════════════════════════════════════════════════════════════════
# 書籍掃描處理
# ══════════════════════════════════════════════════════════════════════════
_BOOK_PROMPT = """你是投資書籍閱讀助理。以下是一本投資書籍掃描章節的 OCR 全文，請整理成讀書筆記。

【全文】
{text}

【輸出：只回傳 JSON，不要其他文字】
{{
  "book": "書名（若文中可辨識，否則null）",
  "author": "作者（若文中可辨識，否則null）",
  "chapter": "本段章節主題（15字內）",
  "summary": "章節摘要（3~5句）",
  "key_concepts": ["核心概念1（一句話講清楚）", "核心概念2", "核心概念3"],
  "quotes": ["值得記住的原文金句1", "金句2"],
  "apply": ["投資實務上怎麼應用1", "怎麼應用2"]
}}"""

_BOOK_FULL_PAGES = 50  # 書籍章節重新 OCR 的頁數上限


def _process_book(pdf: Path, text: str, was_ocr: bool) -> None:
    # 偵測用的 OCR 只轉了前 8 頁；確定是書籍後補轉完整章節
    if was_ocr:
        full = _ocr_text(pdf, max_pages=_BOOK_FULL_PAGES)
        if len(full.strip()) > len(text.strip()):
            text = full

    info = None
    if gem.is_configured():
        try:
            raw = gem.generate(_BOOK_PROMPT.format(text=text[:20000]))
            raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw.strip())
            info = json.loads(raw)
        except Exception as e:
            print(f"  ⚠️  Gemini 萃取失敗：{e}")
    if not info:
        info = {"book": None, "author": None, "chapter": pdf.stem[:20],
                "summary": "", "key_concepts": [], "quotes": [], "apply": []}

    book    = info.get("book") or "未知書籍"
    author  = info.get("author") or ""
    chapter = info.get("chapter") or pdf.stem[:20]
    kc = "\n".join(f"- {c}" for c in info.get("key_concepts", []))
    qt = "\n".join(f"> {q}" for q in info.get("quotes", []))
    ap = "\n".join(f"- {a}" for a in info.get("apply", []))

    md = f"""---
date: {datetime.now().strftime("%Y-%m-%d")}
source: 書籍掃描
book: {book}
author: {author}
chapter: {chapter}
tags: [書籍筆記]
original_file: {pdf.name}
---

# {book}｜{chapter}

## 章節摘要
{info.get("summary", "")}

## 核心概念
{kc or "（見全文）"}

## 重點金句
{qt or "（見全文）"}

## 投資上怎麼用
{ap or "（見全文）"}

---

## 附錄：OCR 全文

{text}
"""
    book_slug = re.sub(r"[^\w一-鿿]", "", book)[:30] or "未知書籍"
    out_dir = KB_DIR.parent / "書籍筆記" / book_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{pdf.stem}.md").write_text(md, encoding="utf-8")
    print(f"  ✅ [書籍] → {out_dir.relative_to(VAULT)}/{pdf.stem}.md")

    dest = ARCHIVE_DIR / "書籍" / pdf.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf), str(dest))
    print(f"  📦 PDF → {dest.relative_to(VAULT)}")


# ══════════════════════════════════════════════════════════════════════════
# 未知類型
# ══════════════════════════════════════════════════════════════════════════
def _process_unknown(pdf: Path, text: str):
    print(f"  ❓ 無法判斷類型，請人工確認：{pdf.name}")
    out_dir = KB_DIR / "_未分類"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = f"""---
date: {datetime.now().strftime("%Y-%m-%d")}
source: 未知
tags: [待分類]
original_file: {pdf.name}
---

# {pdf.stem}（未分類）

> ⚠️ 自動識別失敗，以下為原文前段，請人工補充分類。

```
{text[:1500]}
```
"""
    (out_dir / f"{pdf.stem}.md").write_text(md, encoding="utf-8")
    print(f"  📝 暫存 → 知識庫/個股/_未分類/{pdf.stem}.md（PDF 保留在待閱讀區）")


# ══════════════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════════════
def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("""
 ╔══════════════════════════════════════════════════╗
 ║   📚  StockBrain 統一閱讀器                        ║
 ║                                                  ║
 ║   自動判斷 PDF 類型並分別整理：                      ║
 ║     📰 投資家日報  → 知識庫/個股/投資家日報           ║
 ║     📑 投顧報告    → 知識庫/個股/投顧報告             ║
 ║     📖 書籍掃描    → 知識庫/書籍筆記                  ║
 ║     ❓ 無法判斷    → 知識庫/個股/_未分類（人工確認）   ║
 ║     🔎 掃描檔自動 Gemini OCR，免手動轉檔             ║
 ╚══════════════════════════════════════════════════╝
""")
    print(f"📂 待閱讀區：{PENDING_DIR}\n")

    if not PENDING_DIR.exists():
        print(f"❌ 待閱讀區不存在：{PENDING_DIR}")
        return

    pdfs = sorted(PENDING_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    if not pdfs:
        print("📭 待閱讀區沒有 PDF。把 PDF 放進待閱讀區後再執行。")
        return

    print(f"🔍 掃描到 {len(pdfs)} 個 PDF ...\n")
    results = {"daily": 0, "broker": 0, "book": 0, "unknown": 0}
    labels  = {"daily": "投資家日報", "broker": "投顧報告", "book": "書籍", "unknown": "未知"}

    for pdf in pdfs:
        print(f"📄 {pdf.name}")
        text = _read_text(pdf)
        # 掃描器有時會留幾個字的浮水印文字層，門檻放寬到 40 字才視為有效文字
        was_ocr = len(text.strip()) < 40
        if was_ocr:
            text = _ocr_text(pdf)
        if not text.strip():
            print("  ❌ 無法讀取文字，跳過。")
            continue

        kind = _detect(pdf, text)
        print(f"  🏷️  類型識別：{labels[kind]}")

        if kind == "daily":
            _process_daily(pdf, text)
        elif kind == "broker":
            _process_broker(pdf, text)
        elif kind == "book":
            _process_book(pdf, text, was_ocr)
        else:
            _process_unknown(pdf, text)
        results[kind] += 1
        print()

    print("─" * 48)
    print(f"🎉 完成！投資家日報 {results['daily']} 份　投顧報告 {results['broker']} 份　"
          f"書籍 {results['book']} 份　待確認 {results['unknown']} 份")
    print(f"""
📁 MD 存入位置：
   {KB_DIR.parent}
📦 原始 PDF 已移至：
   {ARCHIVE_DIR}""")


if __name__ == "__main__":
    main()
