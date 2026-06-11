"""📲 推播：Telegram Bot（統一推播管道，以後其他通知也走這）。

需在 .env 設 TELEGRAM_TOKEN（找 @BotFather /newbot 拿）與 TELEGRAM_CHAT_ID。
拿 chat_id：先跟你的 bot 傳一句話，再呼叫 get_chat_id()。
全部 best-effort：沒設定或失敗都只回 (False, 原因)，不讓排程中斷。
"""
from __future__ import annotations

import os

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX = 3900  # Telegram 單則上限 4096，留餘裕


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _chunks(text: str) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > _MAX:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out or [text]


def send(text: str) -> tuple[bool, str]:
    """推一則訊息（過長自動分段）。回 (成功, 訊息)。"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False, "未設定 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID"
    try:
        for chunk in _chunks(text):
            r = requests.post(
                _API.format(token=token, method="sendMessage"),
                json={"chat_id": chat, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )
            if r.status_code != 200:
                return False, f"Telegram {r.status_code}: {r.text[:160]}"
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def get_chat_id() -> str:
    """設定輔助：跟 bot 傳過話後呼叫，找出你的 chat_id。"""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        return "（先在 .env 設 TELEGRAM_TOKEN）"
    try:
        r = requests.get(_API.format(token=token, method="getUpdates"), timeout=20)
        data = r.json()
        for upd in reversed(data.get("result", [])):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat", {})
            if chat.get("id"):
                return f"chat_id = {chat['id']}（對方：{chat.get('first_name') or chat.get('title') or '?'}）"
        return "查無訊息：請先在 Telegram 跟你的 bot 傳一句話，再執行一次。"
    except Exception as e:  # noqa: BLE001
        return f"錯誤：{type(e).__name__}: {e}"
