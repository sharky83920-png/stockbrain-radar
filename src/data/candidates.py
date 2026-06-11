"""選股雷達的候選池（要掃描評分的股票清單）。

存成 Google Drive 的 JSON（跨機同步、可手動編輯）。第一次自動用種子名單建檔。
不硬掃全市場 1800 檔（FinMind 無 token 會被限速），改鎖定一批熱門/成長股。
路徑可用環境變數 RADAR_CANDIDATES_PATH 覆寫。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT = r"G:\我的雲端硬碟\stockbrain\工具欄\radar_candidates.json"

# 種子：AI/半導體/CoWoS/載板/伺服器/記憶體/重電/網通 等熱門題材代表股
_SEED = [
    "2330", "2454", "3661", "3443", "2379", "3035", "6533",  # IC 設計/晶圓
    "3037", "3711", "6515", "3017", "3324",                    # 載板/封測/散熱
    "2317", "2382", "3231", "2376", "4938", "6669",            # 伺服器/組裝
    "2337", "2408", "3006",                                    # 記憶體
    "1503", "1513", "1519", "2308",                            # 重電/電源
    "4979", "3450", "2345",                                    # 網通/光通訊
    "1605", "2603",                                            # 其他熱門
]


def _path() -> Path:
    return Path(os.environ.get("RADAR_CANDIDATES_PATH", _DEFAULT))


def load() -> list[str]:
    """回候選股代號清單。檔案不存在就用種子建檔。"""
    p = _path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_SEED, ensure_ascii=False, indent=2), encoding="utf-8")
        return list(_SEED)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # 容許 ["2330",...] 或 [{"sid":"2330"},...]
        return [d["sid"] if isinstance(d, dict) else str(d) for d in data]
    except Exception:
        return list(_SEED)
