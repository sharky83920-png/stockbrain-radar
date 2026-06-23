"""
投資家日報 自動整理腳本

流程：
  待閱讀區/*.pdf
    → 讀全文（pdfplumber）
    → Gemini 萃取結構化摘要
    → 寫 MD → 知識庫/個股/{sid}_{name}/投資家日報/
    → 移原始 PDF → 原始資料庫（原始格式）/投資家日報/

使用：python scripts/read_investor_daily.py
      python scripts/read_investor_daily.py --dry-run  （只讀不移檔）
"""
from __future__ import annotations

import argparse
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

# ── 路徑常數 ────────────────────────────────────────────────────────────────
VAULT = Path(os.getenv("RADAR_VAULT_DIR", r"G:\我的雲端硬碟\stockbrain"))
PENDING_DIR     = VAULT / "待閱讀區"
KNOWLEDGE_DIR   = VAULT / "知識庫" / "個股"
ARCHIVE_DIR     = VAULT / "原始資料庫（原始格式）" / "投資家日報"

# 投資家日報的關鍵字，用來識別（避免把凱基報告也一起吃掉）
DAILY_MARKERS = ["投資家日報", "孫慶龍", "投資家觀點", "InvestorDaily"]


def _is_investor_daily(pdf_path: Path) -> bool:
    """快速判斷是否為投資家日報（看檔名或首頁關鍵字）。"""
    name = pdf_path.name
    if any(m in name for m in DAILY_MARKERS):
        return True
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            first = pdf.pages[0].extract_text() or ""
            return any(m in first for m in DAILY_MARKERS)
    except Exception:
        return False


def _extract_text(pdf_path: Path) -> str:
    """讀全文（pdfplumber）。"""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        print(f"  ⚠️  PDF 讀取失敗：{e}")
        return ""


_PROMPT = """你是台股投資研究助理。以下是《投資家日報》一份日報的全文，請依指定格式萃取。

【全文】
{text}

【輸出格式：嚴格回傳以下 JSON，不要多餘說明】
{{
  "date": "YYYY-MM-DD",
  "stocks": [{{"sid": "4位代號", "name": "公司中文名"}}],
  "theme": "本期主題（15字內）",
  "industry": "產業（如 AI測試/半導體/金融）",
  "core_thesis": "核心投資邏輯（2~4句）",
  "key_points": ["重點1", "重點2", "重點3"],
  "key_data": ["數據1（如：ASIC 導入 Burn-in，測試時間增3倍）", "數據2"],
  "risk": "主要風險（1~2句，若文中未提則填 null）",
  "outlook": "展望或結論（1~2句）"
}}
"""


def _call_gemini(text: str) -> dict | None:
    """呼叫 Gemini 萃取結構化資訊。"""
    if not gem.is_configured():
        print("  ⚠️  未設定 GEMINI_KEY，改用純文字萃取。")
        return None
    try:
        prompt = _PROMPT.format(text=text[:6000])
        raw = gem.generate(prompt)
        # 去掉可能的 markdown code block
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
        return json.loads(raw)
    except Exception as e:
        print(f"  ⚠️  Gemini 萃取失敗：{e}")
        return None


def _fallback_parse(text: str, filename: str) -> dict:
    """Gemini 不可用時的基本 regex 萃取。"""
    date_m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    date = (f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
            if date_m else datetime.now().strftime("%Y-%m-%d"))

    sid_m = re.findall(r"\((\d{4})\)", text)
    stocks = [{"sid": s, "name": ""} for s in dict.fromkeys(sid_m[:3])]

    return {
        "date": date,
        "stocks": stocks,
        "theme": filename[:30],
        "industry": "",
        "core_thesis": text[200:500].replace("\n", " "),
        "key_points": [],
        "key_data": [],
        "risk": None,
        "outlook": "",
    }


def _build_md(info: dict, source_filename: str) -> str:
    """組成 Obsidian MD 格式。"""
    stocks_str = "、".join(f"{s['name']}({s['sid']})" for s in info.get("stocks", []))
    tags = ["投資家日報"] + [s["sid"] for s in info.get("stocks", [])]
    if info.get("industry"):
        tags.append(info["industry"])

    key_points = "\n".join(f"- {p}" for p in info.get("key_points", []))
    key_data    = "\n".join(f"- {d}" for d in info.get("key_data", []))
    risk_line   = info.get("risk") or "（本期未明確提及）"

    return f"""---
date: {info["date"]}
source: 投資家日報（孫慶龍）
stocks: {stocks_str}
theme: {info.get("theme", "")}
industry: {info.get("industry", "")}
tags: [{", ".join(tags)}]
original_file: {source_filename}
---

# {info["date"]}｜{info.get("theme", "")}

> **標的**：{stocks_str}　｜　**產業**：{info.get("industry", "")}

## 核心論點

{info.get("core_thesis", "")}

## 重點摘要

{key_points if key_points else "（見原文）"}

## 關鍵數據

{key_data if key_data else "（見原文）"}

## 展望

{info.get("outlook", "")}

## 風險

{risk_line}

---
*來源：投資家日報 {info["date"]}　整理日：{datetime.now().strftime("%Y-%m-%d")}*
"""


def process_pdf(pdf_path: Path, dry_run: bool = False) -> bool:
    """處理單一 PDF，回傳是否成功。"""
    print(f"\n📄 {pdf_path.name}")

    text = _extract_text(pdf_path)
    if not text.strip():
        print("  ❌ 無法讀取文字，跳過。")
        return False

    info = _call_gemini(text) or _fallback_parse(text, pdf_path.name)

    # ── 確認至少有一檔股票 ──
    stocks = info.get("stocks") or []
    if not stocks:
        print("  ⚠️  未識別到股票代號，仍寫入 _未分類 資料夾。")
        stocks = [{"sid": "_未分類", "name": ""}]
        info["stocks"] = stocks

    md_content = _build_md(info, pdf_path.name)
    date_str = info.get("date", datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    theme_slug = re.sub(r"[^\w一-鿿]", "", info.get("theme", ""))[:20]

    if not dry_run:
        # ── 寫 MD（每檔主要股票各寫一份，內容相同）──
        for stock in stocks[:1]:  # 只寫主要股（第一檔）
            sid, name = stock["sid"], stock.get("name", "")
            folder_name = f"{sid}_{name}" if name else sid
            kb_dir = KNOWLEDGE_DIR / folder_name / "投資家日報"
            kb_dir.mkdir(parents=True, exist_ok=True)

            md_filename = f"{date_str}_{theme_slug}.md"
            md_path = kb_dir / md_filename
            md_path.write_text(md_content, encoding="utf-8")
            print(f"  ✅ MD 寫入：{md_path.relative_to(VAULT)}")

        # ── 移原始 PDF 到 原始資料庫 ──
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = ARCHIVE_DIR / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        print(f"  📦 PDF 移至：{dest.relative_to(VAULT)}")
    else:
        print(f"  [DRY-RUN] 會寫 MD → 知識庫/個股/{stocks[0]['sid']}_{stocks[0].get('name','')}/投資家日報/")
        print(f"  [DRY-RUN] 核心論點：{info.get('core_thesis','')[:80]}…")

    return True


def main():
    parser = argparse.ArgumentParser(description="投資家日報自動整理")
    parser.add_argument("--dry-run", action="store_true", help="只讀取不移動檔案")
    parser.add_argument("--all", action="store_true", help="處理所有 PDF（不只投資家日報）")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    if not PENDING_DIR.exists():
        print(f"❌ 待閱讀區不存在：{PENDING_DIR}")
        return

    pdfs = sorted(PENDING_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    if not pdfs:
        print("📭 待閱讀區沒有 PDF。")
        return

    print(f"🔍 掃描到 {len(pdfs)} 個 PDF …")
    ok = 0
    for pdf in pdfs:
        if args.all or _is_investor_daily(pdf):
            if process_pdf(pdf, dry_run=args.dry_run):
                ok += 1
        else:
            print(f"  ⏭️  跳過（非投資家日報）：{pdf.name}")

    print(f"\n🎉 完成，共整理 {ok} 份。")


if __name__ == "__main__":
    main()
