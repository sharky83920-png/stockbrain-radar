"""事件前提醒（Telegram）。

每天排程跑一次：抓前瞻事件，只在「事件前 1~2 天」推一則 Telegram 提醒。
沒有近期事件就靜默結束，不打擾。

排程：Windows 工作排程器每天早上跑一次（見 run_event_reminder.bat）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.data import macro_data
from src.data import notify

# 事件前幾天提醒（1=明天、2=後天）
WHEN = {1: "明天", 2: "後天"}


def build_message() -> str | None:
    events = macro_data.upcoming_events()
    imminent = [e for e in events if e["days"] in WHEN]
    if not imminent:
        return None
    lines = ["⏰ 近期事件提醒"]
    for e in imminent:
        when = WHEN[e["days"]]
        lines.append(f"• {when}（{e['date']}）{e['name']}〔{e['market']}〕")
        lines.append(f"   └ {e['hint']}")
    lines.append("\n— StockBrain 事件雷達")
    return "\n".join(lines)


def main() -> None:
    msg = build_message()
    if msg is None:
        print("近 1~2 天無重要事件，不推播。")
        return
    if not notify.is_configured():
        print("Telegram 未設定（TELEGRAM_TOKEN / CHAT_ID），略過推播。內容如下：\n")
        print(msg)
        return
    ok, info = notify.send(msg)
    print("已推播 Telegram。" if ok else f"推播失敗：{info}")
    print("\n--- 推播內容 ---\n" + msg)


if __name__ == "__main__":
    main()
