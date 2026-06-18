"""
投顧報告監控系統
支持自動監控 + 手動掃描
"""
import time
import os
from pathlib import Path
from dotenv import load_dotenv

# 立即加載 .env（在導入其他模塊之前）
load_dotenv()  # 自動找當前目錄的 .env

from src.utils.report_processor import ReportProcessor


class ReportMonitor:
    """監控和處理投顧報告"""

    def __init__(self):
        self.processor = ReportProcessor()
        self.is_running = False

    def manual_scan(self) -> str:
        """
        手動掃描一次
        用戶可在任何對話窗調用：「處理待閱讀區」或「掃描報告」
        """
        print("\n" + "="*60)
        print("🔍 開始手動掃描...")
        print("="*60)

        result = self.processor.process_all_pending()
        message = self.processor.format_results(result)

        print(message)
        return message

    def start_auto_monitor(self, interval: int = 300, max_iterations: int = None):
        """
        啟動自動監控
        定期掃描 Google Drive 待閱讀區

        Args:
            interval: 掃描間隔（秒），默認 300 秒（5 分鐘）
            max_iterations: 最大迭代次數（None = 無限運行）
        """
        self.is_running = True
        iteration = 0

        print("\n" + "="*60)
        print(f"🚀 啟動自動監控（每 {interval} 秒掃描一次）")
        print("="*60)

        try:
            while self.is_running:
                iteration += 1

                if max_iterations and iteration > max_iterations:
                    print(f"\n✅ 已完成 {max_iterations} 次掃描，停止監控")
                    break

                print(f"\n【第 {iteration} 次掃描】 {self._get_timestamp()}")

                result = self.processor.process_all_pending()
                count = result.get("count", 0)

                if count > 0:
                    print(f"✅ 處理了 {count} 份報告")
                else:
                    print(f"🔍 沒有新報告")

                # 等待直到下次掃描
                if self.is_running and not (max_iterations and iteration >= max_iterations):
                    print(f"⏳ 等待 {interval} 秒後下次掃描...")
                    time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n⛔ 監控已停止（用戶中斷）")
            self.is_running = False
        except Exception as e:
            print(f"\n❌ 監控異常：{e}")
            self.is_running = False

    def stop_auto_monitor(self):
        """停止自動監控"""
        self.is_running = False
        print("⛔ 已停止自動監控")

    @staticmethod
    def _get_timestamp() -> str:
        """獲取當前時間戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 全局監控器實例
_monitor_instance = None


def get_monitor() -> ReportMonitor:
    """獲取全局監控器實例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ReportMonitor()
    return _monitor_instance


def manual_scan() -> str:
    """
    手動掃描一次（供對話窗調用）
    使用方式：
        from src.utils.report_monitor import manual_scan
        result = manual_scan()
        print(result)
    """
    monitor = get_monitor()
    return monitor.manual_scan()


def start_monitor(interval: int = 300):
    """
    啟動自動監控（供命令行或後台調用）
    使用方式：
        from src.utils.report_monitor import start_monitor
        start_monitor(interval=300)  # 每 5 分鐘掃描一次
    """
    monitor = get_monitor()
    monitor.start_auto_monitor(interval=interval)
