"""我的清單（暫存/收藏）——存進 Obsidian vault 的 JSON，跨機由 Google Drive 同步。

路徑可用環境變數 RADAR_WATCHLIST_PATH 覆寫（換 Mac 時設定）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT = r"G:\我的雲端硬碟\stockbrain\工具欄\radar_watchlist.json"


def _path() -> Path:
    return Path(os.environ.get("RADAR_WATCHLIST_PATH", _DEFAULT))


def load() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add(sid: str, name: str | None = None) -> None:
    items = load()
    if any(i["sid"] == sid for i in items):
        return
    items.append({"sid": sid, "name": name or sid})
    _save(items)


def remove(sid: str) -> None:
    _save([i for i in load() if i["sid"] != sid])


def contains(sid: str) -> bool:
    return any(i["sid"] == sid for i in load())
