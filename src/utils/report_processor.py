"""
投顧報告處理器
協調監控、PDF 轉換、知識庫管理
"""
from pathlib import Path
from typing import Dict, List
from src.utils.google_drive_monitor import GoogleDriveMonitor
from src.utils.pdf_to_md import PDFToMarkdown
from src.utils.knowledge_base_manager import KnowledgeBaseManager


class ReportProcessor:
    """主処理器：協調所有模塊"""

    def __init__(self):
        self.monitor = GoogleDriveMonitor()
        self.pdf_converter = PDFToMarkdown()
        self.kb_manager = KnowledgeBaseManager(self.monitor.KB_DIR)

    def process_single_pdf(self, pdf_path: Path) -> Dict:
        """處理單份 PDF 報告"""
        result = {
            "filename": pdf_path.name,
            "success": False,
            "data": None,
            "markdown_saved": False,
            "pdf_moved": False,
        }

        try:
            # 1. PDF → 數據 + Markdown
            conversion = self.pdf_converter.process_pdf(pdf_path)
            if not conversion or not conversion.get("success"):
                print(f"❌ 轉換失敗：{pdf_path.name}")
                self.monitor.mark_as_failed(pdf_path.name)
                return result

            data = conversion.get("data")
            markdown = conversion.get("markdown")

            result["data"] = data

            # 2. 存檔到知識庫
            saved = self.kb_manager.save_report(data, markdown)
            result["markdown_saved"] = saved

            if not saved:
                self.monitor.mark_as_failed(pdf_path.name)
                return result

            # 3. 移動 PDF 到閱讀完畢區
            moved = self.monitor.move_to_completed(pdf_path)
            result["pdf_moved"] = moved

            # 4. 標記為已處理
            self.monitor.mark_as_processed(pdf_path.name)

            result["success"] = True
            return result

        except Exception as e:
            print(f"❌ 處理異常：{e}")
            self.monitor.mark_as_failed(pdf_path.name)
            return result

    def process_all_pending(self) -> Dict:
        """處理所有待閱讀報告"""
        pending = self.monitor.scan_pending_reports()

        if not pending:
            return {
                "status": "沒有待處理報告",
                "count": 0,
                "results": [],
            }

        results = []
        for pdf_path in pending:
            result = self.process_single_pdf(pdf_path)
            if result["success"]:
                results.append({
                    "filename": result["filename"],
                    "company": result["data"].get("company"),
                    "code": result["data"].get("code"),
                    "target_price": result["data"].get("target_price"),
                    "upside": result["data"].get("upside"),
                    "rating": result["data"].get("rating"),
                })

        return {
            "status": "完成",
            "count": len(results),
            "results": results,
        }

    def format_results(self, process_result: Dict) -> str:
        """格式化處理結果為可讀的訊息"""
        status = process_result.get("status")
        count = process_result.get("count", 0)
        results = process_result.get("results", [])

        if count == 0:
            return "🔍 沒有待處理的投顧報告"

        output = f"✅ 已讀取 {count} 份投顧報告：\n\n"

        for report in results:
            output += f"**{report.get('company')}({report.get('code')})**\n"
            output += f"• 評等：{report.get('rating', '—')}\n"
            output += f"• 目標價：{report.get('target_price')} 元\n"
            output += f"• 上漲空間：{report.get('upside')}%\n\n"

        output += "✅ **已自動完成：**\n"
        output += "• Claude 智能摘要\n"
        output += "• 存檔到知識庫\n"
        output += "• PDF 移動到閱讀完畢區\n"

        return output
