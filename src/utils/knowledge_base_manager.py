"""
知識庫管理模組
按股票代碼分類、存檔 Markdown 文件
"""
from pathlib import Path
from typing import Dict
from datetime import datetime


class KnowledgeBaseManager:
    """管理知識庫的分類和存檔"""

    def __init__(self, kb_base_path: Path):
        """
        初始化知識庫管理器

        Args:
            kb_base_path: 知識庫根目錄，如 G:/我的雲端硬碟/stockbrain/知識庫/個股
        """
        self.kb_base = kb_base_path

    def save_report(self, data: Dict, markdown: str) -> bool:
        """
        存檔投顧報告

        Args:
            data: 提取的結構化數據（包含 code, company, date, source）
            markdown: 生成的 Markdown 內容

        Returns:
            是否成功存檔
        """
        code = data.get("code")
        company = data.get("company", "未知")
        date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        source = data.get("source", "未知券商")  # 新增：提取來源券商

        if not code:
            print(f"❌ 缺少股票代號，無法存檔")
            return False

        # 建立目錄：知識庫/個股/2317_鴻海/投顧報告/
        report_dir = self.kb_base / f"{code}_{company}" / "投顧報告"
        report_dir.mkdir(parents=True, exist_ok=True)

        # 生成檔案名：[券商]_[日期].md
        # 格式：凱基_2026-05-26.md、Quanta_2026-05-15.md
        filename = f"{source}_{date}.md"
        filepath = report_dir / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(markdown)
            print(f"✅ 已存檔：{code}_{company} → {report_dir.name}/ ({source})")
            return True
        except Exception as e:
            print(f"❌ 存檔失敗：{e}")
            return False

    def get_report_list(self, code: str) -> list:
        """獲取某股票的所有投顧報告"""
        stock_dirs = list(self.kb_base.glob(f"{code}_*/投顧報告"))
        if not stock_dirs:
            return []

        reports = []
        for report_dir in stock_dirs:
            md_files = list(report_dir.glob("*.md"))
            reports.extend([f.name for f in md_files])

        return sorted(reports, reverse=True)

    def get_all_stocks(self) -> list:
        """獲取知識庫中所有已分類的股票"""
        stock_dirs = list(self.kb_base.glob("*_*/"))
        stocks = []
        for d in stock_dirs:
            parts = d.name.rsplit("_", 1)
            if len(parts) == 2:
                code, company = parts
                stocks.append({"code": code, "company": company})
        return sorted(stocks, key=lambda x: x["code"])

    def generate_index(self) -> str:
        """生成知識庫索引"""
        stocks = self.get_all_stocks()

        index = "# 投顧報告知識庫索引\n\n"
        for stock in stocks:
            code = stock["code"]
            company = stock["company"]
            reports = self.get_report_list(code)

            index += f"## {code} - {company}\n"
            if reports:
                for report in reports:
                    index += f"- {report}\n"
            else:
                index += "- （無報告）\n"
            index += "\n"

        return index
