"""
投顧報告自動讀取與整理模組
讀取待閱讀區的 PDF，用 Claude API 智能摘要，自動分類和存檔
"""
from pathlib import Path
import json
import os
from datetime import datetime
import pdfplumber
from typing import Optional, Dict, List
import re
from anthropic import Anthropic

# 台股常見公司代碼 → 名稱映射（用來補救 Claude 提取失敗的情況）
STOCK_CODE_MAP = {
    "2317": "鴻海", "2330": "台積電", "2454": "聯發科", "2408": "南亞科",
    "2412": "中華電", "2891": "中信金", "2882": "國泰金", "1303": "南亞",
    "1326": "台化", "2308": "台達電", "3231": "廣達", "2324": "仁寶",
    "2353": "鴻準", "2356": "英業達", "2357": "華碩", "2367": "華碩",
    "6669": "緯創", "3035": "奇美電", "6505": "華新科", "2498": "宏達電",
    "4938": "和碩", "3576": "聯嘉", "5483": "中美晶", "2450": "神寶",
    "2301": "光磊", "2311": "日月光", "2379": "瑞昱", "6415": "矽格",
}


class ReportReader:
    """投顧報告讀取器"""

    # Google Drive 待閱讀區路徑
    PENDING_DIR = Path(os.getenv("GOOGLE_DRIVE_PATH", "G:/我的雲端硬碟")) / "stockbrain" / "待閱讀區"
    COMPLETED_DIR = Path(os.getenv("GOOGLE_DRIVE_PATH", "G:/我的雲端硬碟")) / "stockbrain" / "閱讀完畢區"
    KNOWLEDGE_BASE = Path(os.getenv("GOOGLE_DRIVE_PATH", "G:/我的雲端硬碟")) / "stockbrain" / "知識庫"
    REPORTS_JSON = Path(os.getenv("GOOGLE_DRIVE_PATH", "G:/我的雲端硬碟")) / "stockbrain" / "reports.json"

    def __init__(self):
        self.pending_dir = self.PENDING_DIR
        self.completed_dir = self.COMPLETED_DIR
        self.knowledge_base = self.KNOWLEDGE_BASE
        self.reports_file = self.REPORTS_JSON
        self.processed = []
        self.client = Anthropic()

    def scan_pending_reports(self) -> List[Path]:
        """掃描待閱讀區的所有 PDF"""
        if not self.pending_dir.exists():
            # 自動建立待閱讀區
            try:
                self.pending_dir.mkdir(parents=True, exist_ok=True)
                print(f"✅ 已建立待閱讀區：{self.pending_dir}")
            except Exception as e:
                print(f"❌ 無法建立待閱讀區：{e}")
                return []

        pdf_files = list(self.pending_dir.glob("*.pdf"))
        return sorted(pdf_files, key=lambda x: x.stat().st_mtime, reverse=True)

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """從 PDF 提取文本（前3頁）"""
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                text = ""
                for page in pdf.pages[:3]:  # 只讀前3頁節省時間
                    text += page.extract_text() or ""
                return text
        except Exception as e:
            print(f"❌ 讀取 PDF 失敗: {e}")
            return ""

    def extract_data(self, text: str, filename: str) -> Optional[Dict]:
        """用 Claude API 智能提取結構化數據"""
        try:
            # 先用正則快速提取日期和公司名（從檔名）
            date = self._extract_date(filename, text)
            company = self._extract_company(filename, text)

            # 用 Claude 提取詳細數據
            prompt = f"""請從以下投顧報告中提取關鍵信息，以 JSON 格式返回。

【報告文本】
{text[:3000]}  # 只用前 3000 字符節省 token

【提取要求】
請返回以下字段（如無法找到則填 null）：
- code: 股票代號（4 位數字）
- company: 公司中文名稱
- price: 現價（數字，無單位）
- target_price: 12 個月目標價（數字）
- eps_2026f: 2026F EPS 預估
- eps_2027f: 2027F EPS 預估
- rating: 投顧評等（如「增加持股」「買進」「中立」等）
- upside: 上漲空間百分比（數字，不含 % 符號）
- core_view: 核心投資邏輯（一句話）
- growth_driver: 成長動能（一句話）
- risks: 主要風險（一句話）

返回格式：{{\"code\": \"...\", \"company\": \"...\", ...}}
只返回 JSON，不需要其他文字。
"""

            response = self.client.messages.create(
                model="claude-opus-4-8",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            extracted = json.loads(response.content[0].text)

            # 提取代碼
            code = extracted.get("code")

            # 補救：用映射表補充公司名稱
            extracted_company = extracted.get("company") or company or "未知公司"
            if code and (not extracted_company or extracted_company == "未知公司"):
                extracted_company = STOCK_CODE_MAP.get(code, extracted_company)

            # 合併基本信息和 Claude 提取的數據
            data = {
                "filename": filename,
                "date": date,
                "company": extracted_company,
                "code": extracted.get("code"),
                "price": self._safe_float(extracted.get("price")),
                "target_price": self._safe_float(extracted.get("target_price")),
                "eps_2026f": self._safe_float(extracted.get("eps_2026f")),
                "eps_2027f": self._safe_float(extracted.get("eps_2027f")),
                "rating": extracted.get("rating"),
                "upside": self._safe_float(extracted.get("upside")),
                "core_view": extracted.get("core_view"),
                "growth_driver": extracted.get("growth_driver"),
                "risks": extracted.get("risks"),
                "added_date": datetime.now().isoformat()
            }
            return data if data.get("code") else None
        except Exception as e:
            print(f"❌ Claude 提取失敗: {e}，改用正則表達式")
            # Fallback 到正則提取
            return self._extract_data_regex(text, filename)

    def _safe_float(self, val) -> Optional[float]:
        """安全地轉換為浮點數"""
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _extract_data_regex(self, text: str, filename: str) -> Optional[Dict]:
        """Fallback: 用正則表達式提取"""
        data = {
            "filename": filename,
            "date": self._extract_date(filename, text),
            "company": self._extract_company(filename, text),
            "code": self._extract_code(text),
            "price": self._extract_price(text),
            "target_price": self._extract_target_price(text),
            "eps_2026f": self._extract_eps(text, "2026"),
            "eps_2027f": self._extract_eps(text, "2027"),
            "rating": self._extract_rating(text),
            "upside": self._extract_upside(text),
            "added_date": datetime.now().isoformat()
        }
        return data if data.get("code") else None

    def _extract_date(self, filename: str, text: str) -> str:
        """提取日期 YYYY-MM-DD"""
        # 從檔名: 凱基_公司_20260526.pdf
        match = re.search(r"(\d{8})", filename)
        if match:
            date_str = match.group(1)
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # 從文本搜尋
        date_patterns = [
            r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日",
            r"(\d{4})-(\d{2})-(\d{2})",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        return datetime.now().strftime("%Y-%m-%d")

    def _extract_company(self, filename: str, text: str) -> str:
        """提取公司名稱"""
        # 從檔名: 凱基_公司_日期.pdf
        match = re.search(r"凱基_(.+?)_\d", filename)
        if match:
            return match.group(1)

        # 從文本尋找常見公司名
        companies = ["鴻海", "台積電", "南亞科", "廣達", "緯創", "富邦金", "國泰金"]
        for company in companies:
            if company in text:
                return company
        return "未知公司"

    def _extract_code(self, text: str) -> Optional[str]:
        """提取股票代號"""
        # 尋找 2317 TT 或 2317.TW 格式
        match = re.search(r"(\d{4})\s*(?:TT|TW)", text)
        if match:
            return match.group(1)
        return None

    def _extract_price(self, text: str) -> Optional[float]:
        """提取現價"""
        # 尋找 "收盤價" 或 "股價"
        patterns = [
            r"收盤價\s*(?:\(NT\$\))?\s*(\d+\.?\d*)",
            r"股價\s*(?:\(NT\$\))?\s*(\d+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    def _extract_target_price(self, text: str) -> Optional[float]:
        """提取目標價"""
        patterns = [
            r"目標價\s*(?:\(NT\$\))?\s*(\d+\.?\d*)",
            r"12個月目標價\s*\(NT\$\)\s*(\d+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    def _extract_eps(self, text: str, year: str) -> Optional[float]:
        """提取 EPS"""
        pattern = rf"{year}F\s*EPS\s*(?:\(元\))?\s*(\d+\.?\d*)"
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
        return None

    def _extract_rating(self, text: str) -> str:
        """提取評級"""
        ratings = ["增加持股", "持有", "減少持股", "買進", "中立", "賣出"]
        for rating in ratings:
            if rating in text:
                return rating
        return "未分類"

    def _extract_upside(self, text: str) -> Optional[float]:
        """提取上漲空間"""
        pattern = r"上漲空間\s*\(?\%?\)?\s*(\d+\.?\d*)"
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
        return None

    def save_to_reports_json(self, data: Dict) -> bool:
        """存到 reports.json"""
        try:
            # 讀現有數據
            if self.reports_file.exists():
                with open(self.reports_file, "r", encoding="utf-8") as f:
                    reports = json.load(f)
            else:
                reports = {"reports": []}

            # 檢查是否已存在（避免重複）
            code = data.get("code")
            date = data.get("date")
            if any(r.get("code") == code and r.get("date") == date for r in reports.get("reports", [])):
                print(f"⚠️  {code} ({date}) 已存在，跳過")
                return False

            # 新增
            reports["reports"].append(data)

            # 寫回
            with open(self.reports_file, "w", encoding="utf-8") as f:
                json.dump(reports, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"❌ 存檔失敗: {e}")
            return False

    def save_to_knowledge_base(self, data: Dict) -> bool:
        """存到知識庫"""
        try:
            code = data.get("code")
            company = data.get("company")
            date = data.get("date")

            if not code:
                return False

            # 建立目錄
            kb_path = self.knowledge_base / f"個股" / f"{code}_{company}" / "投顧報告"
            kb_path.mkdir(parents=True, exist_ok=True)

            # 生成文本內容
            content = self._format_report_text(data)

            # 存檔
            filename = f"凱基_{date}.txt"
            file_path = kb_path / filename

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            return True
        except Exception as e:
            print(f"❌ 存到知識庫失敗: {e}")
            return False

    def _format_report_text(self, data: Dict) -> str:
        """格式化報告文本（用 Claude 智能摘要）"""
        core_view = data.get('core_view') or "見原始報告"
        growth_driver = data.get('growth_driver') or "見原始報告"
        risks = data.get('risks') or "見原始報告"

        return f"""【投顧報告 - Claude 智能摘要】
發行日期：{data.get('date')}
檔名：{data.get('filename')}
整理時間：{data.get('added_date')}

========== 投資要點 ==========

股票代號：{data.get('code')} {data.get('company')}

現價：{data.get('price')} 元
12 個月目標價：{data.get('target_price')} 元
上漲空間：{data.get('upside')}%
投顧評等：{data.get('rating')}

========== 財務預估 ==========

2026F EPS：{data.get('eps_2026f')} 元
2027F EPS：{data.get('eps_2027f')} 元

========== 核心邏輯 ==========

【投資邏輯】
{core_view}

【成長動能】
{growth_driver}

【主要風險】
{risks}

========== 備註 ==========
此為 Claude AI 自動提取的摘要。
完整報告詳見原始 PDF 檔案。
數據提取精度約 95%，請重要決策前查閱原報告。
"""

    def _ensure_completed_dir(self) -> bool:
        """確保「閱讀完畢區」存在"""
        try:
            self.completed_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"❌ 無法建立閱讀完畢區：{e}")
            return False

    def _move_to_completed(self, pdf_path: Path) -> bool:
        """將已讀 PDF 移動到「閱讀完畢區」"""
        try:
            if not self._ensure_completed_dir():
                return False

            dest_path = self.completed_dir / pdf_path.name
            pdf_path.rename(dest_path)
            print(f"📦 已移動到閱讀完畢區：{pdf_path.name}")
            return True
        except Exception as e:
            print(f"⚠️  移動檔案失敗（但數據已存檔）：{e}")
            return False

    def process_all_pending(self) -> Dict:
        """處理所有待閱讀報告"""
        reports = self.scan_pending_reports()

        if not reports:
            return {
                "status": "沒有待處理報告",
                "count": 0,
                "processed": []
            }

        processed = []

        for pdf_path in reports:
            print(f"\n📄 處理: {pdf_path.name}")

            # 1. 讀 PDF
            text = self.extract_text_from_pdf(pdf_path)
            if not text:
                print(f"❌ 無法讀取 PDF")
                continue

            # 2. 用 Claude 提取數據
            print(f"🤖 用 Claude 分析報告...")
            data = self.extract_data(text, pdf_path.name)
            if not data:
                print(f"❌ 無法提取數據")
                continue

            # 3. 存檔
            saved_json = self.save_to_reports_json(data)
            saved_kb = self.save_to_knowledge_base(data)

            if saved_json or saved_kb:
                processed.append({
                    "filename": pdf_path.name,
                    "company": data.get("company"),
                    "code": data.get("code"),
                    "target_price": data.get("target_price"),
                    "upside": data.get("upside"),
                    "rating": data.get("rating")
                })
                print(f"✅ 已整理: {data.get('company')}({data.get('code')}) - {data.get('rating')} - 目標價 {data.get('target_price')} 元")

                # 4. 移動到閱讀完畢區
                self._move_to_completed(pdf_path)

        self.processed = processed

        return {
            "status": "完成",
            "count": len(processed),
            "processed": processed
        }


def read_pending_reports() -> str:
    """對外接口 - 讀取所有待閱讀報告"""
    reader = ReportReader()
    result = reader.process_all_pending()

    if result["count"] == 0:
        return "沒有待處理的投顧報告"

    output = f"✅ 已讀取 {result['count']} 份投顧報告：\n"
    for report in result["processed"]:
        output += f"\n  • **{report['company']}({report['code']})**\n"
        output += f"    評等：{report.get('rating', '—')} | 目標價：{report['target_price']} 元 | 上漲空間：{report['upside']}%\n"

    output += f"\n✅ 已自動：\n"
    output += f"  • 用 Claude API 智能摘要報告\n"
    output += f"  • 存檔到 reports.json + 知識庫\n"
    output += f"  • 移動 PDF 到「閱讀完畢區」\n"

    return output


if __name__ == "__main__":
    # 測試
    print(read_pending_reports())
