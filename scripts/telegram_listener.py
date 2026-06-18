"""📲 Telegram 雙向：聽你傳給 bot 的訊息，自動加股票進清單並回覆。

你在 Telegram 傳給 @你的bot：
  - 「2454」或「聯發科」 → 加進「我的清單」，回你已加入
  - 「list」或「清單」     → 回目前清單
  - 「remove 2454」或「刪 2454」 → 從清單移除
  - 其他               → 回簡短說明

用 offset 檔記住處理到哪，不重複。排程每幾分鐘跑一次（電腦開著時才會處理）。
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.debate_engine import resolve_stock
from src.data import notify, watchlist

_OFFSET_FILE = Path(__file__).resolve().parents[1] / "data" / "tg_offset.txt"


def _load_offset() -> int | None:
    try:
        return int(_OFFSET_FILE.read_text().strip())
    except Exception:
        return None


def _save_offset(v: int) -> None:
    try:
        _OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_FILE.write_text(str(v), encoding="utf-8")
    except Exception:
        pass


def _handle(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    if low in ("list", "清單", "/list", "我的清單"):
        wl = watchlist.load()
        if not wl:
            return "清單目前是空的。傳股票代號或名稱就能加入。"
        return "⭐ 目前清單：\n" + "\n".join(f"• {i['name']}({i['sid']})" for i in wl)
    m = re.match(r"^(remove|刪除?|del)\s*(.+)$", t, re.I)
    if m:
        sid, name = resolve_stock(m.group(2).strip())
        if sid and watchlist.contains(sid):
            watchlist.remove(sid)
            return f"🗑 已從清單移除 {name or sid}({sid})。"
        return f"清單裡找不到「{m.group(2).strip()}」。"
    if low in ("start", "/start", "hi", "你好", "help", "/help"):
        return ("👋 我是光之國度。\n"
                "・傳股票代號或名稱（例：2454 或 聯發科）→ 加入清單\n"
                "・傳「清單」→ 看目前追蹤\n"
                "・傳「刪 2454」→ 移除\n"
                "排程時段(週一~五 08:00/13:30/18:00/20:30)會自動討論並把摘要推給你。")
    # 其餘當成「要追蹤的股票」
    sid, name = resolve_stock(t)
    if not sid:
        return f"查無「{t}」。可傳股票代號(如 2454)或中文名(如 聯發科)，或傳「清單」看追蹤。"
    if watchlist.contains(sid):
        return f"✓ {name or sid}({sid}) 已經在清單裡了。"
    watchlist.add(sid, name)
    return f"✅ 已把 {name}({sid}) 加入清單，下次討論就會包含它。"


def main() -> None:
    if not notify.is_configured():
        print("未設定 Telegram，略過。")
        return
    offset = _load_offset()
    updates = notify.get_updates(offset + 1 if offset is not None else None)
    if not updates:
        print("沒有新訊息。")
        return
    max_id = offset or 0
    for u in updates:
        max_id = max(max_id, u.get("update_id", 0))
        msg = u.get("message") or {}
        text = msg.get("text")
        if not text:
            continue
        reply = _handle(text)
        ok, info = notify.send(reply)
        print(f"收到「{text}」→ 回覆{'成功' if ok else '失敗:'+info}")
    _save_offset(max_id)


if __name__ == "__main__":
    main()
