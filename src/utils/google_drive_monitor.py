"""
Google Drive 監控模組
掃描待閱讀區、管理配置、處理文件移動
"""
from pathlib import Path
import json
import os
from datetime import datetime
from typing import List, Dict, Optional


class GoogleDriveMonitor:
    """監控 Google Drive 中的投顧報告"""

    # Google Drive 本地挂载路径（Windows 同步文件夹）
    DRIVE_PATH = Path("G:/我的雲端硬碟/stockbrain")
    PENDING_DIR = DRIVE_PATH / "待閱讀區"
    COMPLETED_DIR = DRIVE_PATH / "閱讀完畢區"
    KB_DIR = DRIVE_PATH / "知識庫/個股"
    CONFIG_FILE = DRIVE_PATH / ".processing_config.json"

    def __init__(self):
        """初始化監控器，確保目錄存在"""
        self._ensure_directories()
        self.config = self._load_config()

    def _ensure_directories(self):
        """確保所有必要的目錄存在"""
        for directory in [self.PENDING_DIR, self.COMPLETED_DIR, self.KB_DIR]:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"✅ 已確保目錄存在：{directory.name}")

    def _load_config(self) -> Dict:
        """讀取配置文件"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  讀取配置文件失敗：{e}，使用默認配置")

        # 默認配置
        return {
            "last_scan": None,
            "processed_pdfs": [],
            "stats": {"total": 0, "success": 0, "failed": 0},
        }

    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 保存配置文件失敗：{e}")

    def scan_pending_reports(self) -> List[Path]:
        """掃描待閱讀區的所有 PDF"""
        if not self.PENDING_DIR.exists():
            print(f"❌ 待閱讀區不存在：{self.PENDING_DIR}")
            return []

        pdf_files = list(self.PENDING_DIR.glob("*.pdf"))
        processed = self.config.get("processed_pdfs", [])

        # 過濾掉已處理的 PDF
        pending = [f for f in pdf_files if f.name not in processed]

        print(f"📊 掃描結果：共 {len(pdf_files)} 份 PDF，待處理 {len(pending)} 份")
        return sorted(pending, key=lambda x: x.stat().st_mtime, reverse=True)

    def mark_as_processed(self, filename: str):
        """標記 PDF 為已處理"""
        if filename not in self.config["processed_pdfs"]:
            self.config["processed_pdfs"].append(filename)
            self.config["stats"]["success"] += 1
            self.config["last_scan"] = datetime.now().isoformat()
            self._save_config()

    def mark_as_failed(self, filename: str):
        """標記 PDF 為處理失敗"""
        self.config["stats"]["failed"] += 1
        self.config["stats"]["total"] += 1
        self._save_config()

    def move_to_completed(self, pdf_path: Path) -> bool:
        """移動已讀 PDF 到閱讀完畢區"""
        try:
            dest_path = self.COMPLETED_DIR / pdf_path.name
            pdf_path.rename(dest_path)
            print(f"📦 已移動到閱讀完畢區：{pdf_path.name}")
            return True
        except Exception as e:
            print(f"⚠️  移動檔案失敗：{e}")
            return False

    def get_kb_path(self, code: str, company: str) -> Path:
        """獲取知識庫儲存路徑"""
        # 格式：知識庫/個股/2317_鴻海/投顧報告/
        folder = self.KB_DIR / f"{code}_{company}" / "投顧報告"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def get_config_summary(self) -> str:
        """獲取配置摘要"""
        stats = self.config.get("stats", {})
        return f"""
        📊 **處理統計**
        • 已處理：{stats.get('success', 0)} 份
        • 失敗：{stats.get('failed', 0)} 份
        • 上次掃描：{self.config.get('last_scan', '未掃描過')}
        """
