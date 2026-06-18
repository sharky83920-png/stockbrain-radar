"""
Claude Code 對話窗 PDF 上傳與處理模組
用戶上傳 PDF + 說「閱讀報告」→ 自動讀取、摘要、歸檔
"""
from pathlib import Path
import os
from datetime import datetime
from typing import Optional, Dict
from src.utils.read_reports import ReportReader


# 偵測關鍵字
KEYWORDS = ["閱讀", "读取", "讀取", "讀報告", "閱讀報告", "處理報告", "讀檔案", "閱讀檔案"]


def detect_read_command(user_input: str) -> bool:
    """檢測用戶是否要求讀取報告"""
    return any(keyword in user_input for keyword in KEYWORDS)


def process_uploaded_pdf(file_path: str) -> Dict:
    """
    處理用戶上傳的 PDF 檔案

    Args:
        file_path: PDF 檔案路徑

    Returns:
        處理結果字典
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return {
            "success": False,
            "message": f"❌ 檔案不存在：{file_path}",
            "error": "FILE_NOT_FOUND"
        }

    if not file_path.suffix.lower() == ".pdf":
        return {
            "success": False,
            "message": f"❌ 只支援 PDF 檔案，您上傳的是：{file_path.suffix}",
            "error": "INVALID_FILE_TYPE"
        }

    try:
        # 初始化讀者
        reader = ReportReader()

        print(f"\n📄 開始處理：{file_path.name}")

        # 1. 讀取 PDF 文本
        text = reader.extract_text_from_pdf(file_path)
        if not text:
            return {
                "success": False,
                "message": f"❌ 無法讀取 PDF 內容",
                "error": "PDF_READ_FAILED"
            }

        # 2. 用 Claude 提取數據
        print(f"🤖 用 Claude 分析報告...")
        data = reader.extract_data(text, file_path.name)
        if not data:
            return {
                "success": False,
                "message": f"❌ 無法提取報告數據（可能不是投顧報告格式）",
                "error": "DATA_EXTRACTION_FAILED"
            }

        # 3. 存檔
        saved_json = reader.save_to_reports_json(data)
        saved_kb = reader.save_to_knowledge_base(data)

        if not (saved_json or saved_kb):
            return {
                "success": False,
                "message": f"❌ 存檔失敗",
                "error": "SAVE_FAILED"
            }

        # 4. 成功
        result = {
            "success": True,
            "message": f"✅ 已讀取並歸檔：{data.get('company')}({data.get('code')})",
            "data": {
                "company": data.get("company"),
                "code": data.get("code"),
                "date": data.get("date"),
                "target_price": data.get("target_price"),
                "upside": data.get("upside"),
                "rating": data.get("rating"),
                "core_view": data.get("core_view"),
                "growth_driver": data.get("growth_driver"),
                "risks": data.get("risks"),
            },
            "saved": {
                "reports_json": saved_json,
                "knowledge_base": saved_kb
            }
        }

        # 5. 刪除原檔案（保留在知識庫了）
        try:
            file_path.unlink()
            print(f"📦 已刪除上傳檔案")
        except Exception as e:
            print(f"⚠️  無法刪除檔案（但數據已保存）：{e}")

        return result

    except Exception as e:
        return {
            "success": False,
            "message": f"❌ 處理失敗：{type(e).__name__}: {e}",
            "error": str(e)
        }


def format_result_message(result: Dict) -> str:
    """格式化處理結果為可讀的訊息"""
    if not result.get("success"):
        return result.get("message", "❌ 處理失敗")

    data = result.get("data", {})
    msg = result.get("message", "✅ 成功")
    msg += "\n\n"
    msg += f"📊 **投資要點**\n"
    msg += f"• 代號：{data.get('code')} {data.get('company')}\n"
    msg += f"• 評等：{data.get('rating')}\n"
    msg += f"• 目標價：{data.get('target_price')} 元\n"
    msg += f"• 上漲空間：{data.get('upside')}%\n"

    if data.get("core_view"):
        msg += f"\n💡 **核心邏輯**\n{data.get('core_view')}\n"

    if data.get("growth_driver"):
        msg += f"\n📈 **成長動能**\n{data.get('growth_driver')}\n"

    if data.get("risks"):
        msg += f"\n⚠️ **主要風險**\n{data.get('risks')}\n"

    msg += f"\n✅ **已存檔到知識庫**"

    return msg
