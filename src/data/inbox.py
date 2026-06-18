"""📥 手機清單收件匣。

你在手機 Obsidian 開 `想追蹤的股票.md`，一行一個打股名/代號，存檔。
排程跑之前會 process_inbox()：解析→加進「我的清單」→清空輸入區→把結果記到檔尾。
這樣不用編 JSON，手機就能遠端加追蹤。

路徑可用環境變數 RADAR_INBOX_PATH 覆寫。
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from . import watchlist

_DEFAULT = r"G:\我的雲端硬碟\secondbrain\創作庫\光之國度自動代理人計畫\知識庫\想追蹤的股票.md"
_INPUT_MARK = "## ✏️ 在這行以下輸入（一行一個）"
_DONE_MARK = "## ✅ 已處理紀錄"

_TEMPLATE = f"""---
title: 📥 我想追蹤的股票（手機收件匣）
---
# 📥 想追蹤的股票

> 在下面「一行一個」打股票代號或中文名（例：2330 或 台積電），存檔。
> 排程下次跑之前會自動讀這裡 → 加進「我的清單」→ 清空這區、把結果記到下面。

{_INPUT_MARK}


{_DONE_MARK}
"""


def _path() -> Path:
    return Path(os.environ.get("RADAR_INBOX_PATH", _DEFAULT))


def ensure_file() -> None:
    p = _path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_TEMPLATE, encoding="utf-8")


def process_inbox() -> list[dict]:
    """讀收件匣→解析→加進 watchlist→清空輸入區並記錄結果。回 [{input,sid,name,status}]。"""
    p = _path()
    if not p.exists():
        ensure_file()
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    # 取「輸入區」（兩個標記之間）的內容
    if _INPUT_MARK in text:
        after = text.split(_INPUT_MARK, 1)[1]
        body = after.split(_DONE_MARK, 1)[0] if _DONE_MARK in after else after
    else:
        body = text  # 沒模板就整檔當輸入
    raw_lines = [ln.strip() for ln in body.splitlines()]
    candidates = [ln for ln in raw_lines if ln and not ln.startswith(("#", ">", "-", "<!--"))]

    from src.analysis.debate_engine import resolve_stock  # 延遲匯入避免循環

    results: list[dict] = []
    for c in candidates:
        sid, name = resolve_stock(c)
        if not sid:
            results.append({"input": c, "sid": None, "name": None, "status": "查無此股"})
        elif watchlist.contains(sid):
            results.append({"input": c, "sid": sid, "name": name, "status": "已在清單"})
        else:
            watchlist.add(sid, name)
            results.append({"input": c, "sid": sid, "name": name, "status": "✅ 已加入"})

    # 重寫檔案：清空輸入區，把這次結果追加到「已處理紀錄」
    if results:
        today = dt.date.today().isoformat()
        log_lines = []
        for r in results:
            tail = f"（{r['name']}/{r['sid']}）" if r["sid"] else ""
            log_lines.append(f"- {today} 「{r['input']}」→ {r['status']}{tail}")
        old_done = text.split(_DONE_MARK, 1)[1].strip() if _DONE_MARK in text else ""
        new_text = (
            _TEMPLATE.split(_DONE_MARK)[0] + _DONE_MARK + "\n"
            + "\n".join(log_lines) + ("\n" + old_done if old_done else "") + "\n"
        )
        p.write_text(new_text, encoding="utf-8")
    return results
