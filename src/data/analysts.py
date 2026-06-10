"""我的分析師（名人觀點）——存進 Obsidian vault 的 JSON，跨機由 Google Drive 同步。

路徑可用環境變數 RADAR_ANALYSTS_PATH 覆寫。
預設帶入使用者 SOP 追蹤的 KOL；使用者可在側邊欄加減。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT_PATH = r"G:\我的雲端硬碟\stockbrain\工具欄\radar_analysts.json"

# 預設名單（來自使用者投資 SOP 的 KOL）
DEFAULTS = [
    {"name": "獅公 李永年"},
    {"name": "股魚"},
    {"name": "闕又上"},
    {"name": "蔡豐勝"},
]


def _path() -> Path:
    return Path(os.environ.get("RADAR_ANALYSTS_PATH", _DEFAULT_PATH))


def load() -> list[dict]:
    p = _path()
    if not p.exists():
        return [dict(d) for d in DEFAULTS]  # 首次用：回預設(不寫檔)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return [dict(d) for d in DEFAULTS]


def _save(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add(name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    items = load()
    if any(i["name"] == name for i in items):
        return
    items.append({"name": name})
    _save(items)


def remove(name: str) -> None:
    _save([i for i in load() if i["name"] != name])


def names() -> list[str]:
    return [i["name"] for i in load()]
