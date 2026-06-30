"""自動個股事件雷達：從 TWSE 官方開放資料抓 watchlist 各檔的
法說會 / 股東會 / 除權息日期，寫入 vault 工具欄/個股事件_auto.json。

設計：自動層與手動層（個股事件.json）分開存放，讀取時由 stock_events.upcoming()
合併、**手動優先**。所以自動抓壞了也不影響你手填的事件；自動只是加分。

排程：Windows 工作排程器每日收盤後跑 run_auto_events.bat。

資料源（官方開放資料、免金鑰、乾淨 JSON，比爬 MOPS HTML 穩）：
- 法說會：t187ap04_L 上市每日重大訊息（公司公告當日出現 → 每天跑會逐日累積未來法說會）
- 股東會：t187ap38_L 股東會公告彙總表（整表，含未來日期）
- 除權息：TWT48U_ALL 除權除息預告表（整表，含未來日期）

涵蓋範圍：僅上市(TWSE)。上櫃(TPEX)個股不抓，沿用手動填。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

try:  # Norton 會攔 SSL（見接手文件）
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import urllib3
urllib3.disable_warnings()

from src.data import watchlist

VAULT_DIR = Path(os.environ.get("RADAR_VAULT_DIR", r"G:\我的雲端硬碟\stockbrain"))
AUTO_PATH = Path(os.environ.get(
    "RADAR_STOCK_EVENTS_AUTO_PATH", str(VAULT_DIR / "工具欄" / "個股事件_auto.json")))

URL_ANN = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"      # 每日重大訊息
URL_AGM = "https://openapi.twse.com.tw/v1/opendata/t187ap38_L"      # 股東會公告
URL_DIV = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"  # 除權除息預告

_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url: str) -> list[dict]:
    r = requests.get(url, timeout=30, verify=False, headers=_HDR)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def _roc_to_iso(s: str) -> str | None:
    """民國日期 → YYYY-MM-DD。吃 '1150716' / '115/07/16' / '民國115年7月16日'。"""
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r"(\d{2,3})\D+(\d{1,2})\D+(\d{1,2})", s)  # 115/07/16、115年7月16日
    if not m:
        m = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", s)        # 1150716
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1911:
        y += 1911
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _clean(text: str, limit: int = 60) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:limit]


def _parse_conf_date(desc: str) -> str | None:
    """從法說會重大訊息「說明」抽法說會召開日期。優先抓『召開法人說明會之日期』那一行。"""
    if not desc:
        return None
    m = re.search(r"(?:召開)?法人說明會(?:之)?日期[^0-9]{0,6}"
                  r"(\d{2,3}\D+\d{1,2}\D+\d{1,2}|\d{7})", desc)
    if m:
        iso = _roc_to_iso(m.group(1))
        if iso:
            return iso
    # 退而求其次：說明裡第一個民國日期
    m = re.search(r"(\d{2,3}\D{1,2}\d{1,2}\D{1,2}\d{1,2})", desc)
    return _roc_to_iso(m.group(1)) if m else None


def fetch_conferences(sids: set[str]) -> dict[str, list[dict]]:
    """法說會（來自每日重大訊息；公司公告當天才有，故需每日累積）。"""
    out: dict[str, list[dict]] = {}
    try:
        rows = _get(URL_ANN)
    except Exception as e:
        print(f"  [法說會] 抓取失敗，跳過：{e!r}")
        return out
    for r in rows:
        sid = str(r.get("公司代號", "")).strip()
        if sid not in sids:
            continue
        subj = r.get("主旨 ") or r.get("主旨") or ""
        if "法人說明會" not in subj and "法說會" not in subj:
            continue
        d = _parse_conf_date(r.get("說明", "")) or _roc_to_iso(r.get("事實發生日", ""))
        if d:
            out.setdefault(sid, []).append(
                {"date": d, "type": "法說會", "note": _clean(subj), "source": "auto:重大訊息"})
    return out


def fetch_agm(sids: set[str]) -> dict[str, list[dict]]:
    """股東會。"""
    out: dict[str, list[dict]] = {}
    try:
        rows = _get(URL_AGM)
    except Exception as e:
        print(f"  [股東會] 抓取失敗，跳過：{e!r}")
        return out
    for r in rows:
        sid = str(r.get("公司代號", "")).strip()
        if sid not in sids:
            continue
        d = _roc_to_iso(r.get("股東常(臨時)會日期-日期", ""))
        if d:
            kind = r.get("股東常(臨時)會日期-常或臨時", "") or "股東會"
            cash = r.get("預擬配發現金(股利)(元/股)-盈餘", "")
            note = f"{kind}" + (f"，擬配現金股利 {cash} 元" if cash else "")
            out.setdefault(sid, []).append(
                {"date": d, "type": "股東會", "note": _clean(note), "source": "auto:股東會公告"})
    return out


def fetch_dividends(sids: set[str]) -> dict[str, list[dict]]:
    """除權息預告。"""
    out: dict[str, list[dict]] = {}
    try:
        rows = _get(URL_DIV)
    except Exception as e:
        print(f"  [除權息] 抓取失敗，跳過：{e!r}")
        return out
    for r in rows:
        sid = str(r.get("Code", "")).strip()
        if sid not in sids:
            continue
        d = _roc_to_iso(r.get("Date", ""))
        if not d:
            continue
        tag = r.get("Exdividend", "")  # 息 / 權 / 權息
        typ = "除息" if tag == "息" else ("除權" if tag == "權" else "除權息")
        cash = r.get("CashDividend", "")
        try:
            cash = f"{float(cash):.2f}" if cash else ""
        except (TypeError, ValueError):
            cash = ""
        note = (f"配息 {cash} 元" if cash else tag)
        out.setdefault(sid, []).append(
            {"date": d, "type": typ, "note": _clean(note), "source": "auto:除權息預告"})
    return out


def _merge_into(acc: dict, new: dict) -> None:
    """把 new 併進 acc（以 sid 為 key），同一 (date,type) 不重複。"""
    for sid, evs in new.items():
        bucket = acc.setdefault(sid, [])
        seen = {(e["date"], e["type"]) for e in bucket}
        for e in evs:
            key = (e["date"], e["type"])
            if key not in seen:
                bucket.append(e)
                seen.add(key)


def main() -> None:
    wl = watchlist.load()
    sids = {str(it["sid"]).strip() for it in wl}
    if not sids:
        print("watchlist 是空的，沒東西可抓。")
        return
    print(f"自動事件雷達：掃 {len(sids)} 檔 {sorted(sids)}")

    # 法說會來自「每日重大訊息」（公告當天才有），需逐日累積：保留舊檔的法說會當基底。
    # 股東會/除權息來自「完整表」，每次重抓最新（自動覆蓋，修正過的配息會更新）。
    acc: dict[str, list[dict]] = {}
    if AUTO_PATH.exists():
        try:
            old = json.loads(AUTO_PATH.read_text(encoding="utf-8"))
            for sid, evs in old.items():
                if isinstance(evs, list):
                    conf = [e for e in evs if isinstance(e, dict) and e.get("type") == "法說會"]
                    if conf:
                        acc[sid] = conf
        except Exception:
            acc = {}

    _merge_into(acc, fetch_conferences(sids))  # 累積
    _merge_into(acc, fetch_agm(sids))          # 完整表，最新
    _merge_into(acc, fetch_dividends(sids))    # 完整表，最新

    # 清掉已過期事件（保留今天起的未來事件），順便排序
    today = date.today().isoformat()
    total = 0
    for sid in list(acc.keys()):
        kept = sorted((e for e in acc[sid] if e.get("date", "") >= today),
                      key=lambda e: e["date"])
        if kept:
            acc[sid] = kept
            total += len(kept)
        else:
            del acc[sid]

    AUTO_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = {"_說明": "自動產生，請勿手動編輯。手動事件請編 個股事件.json（讀取時手動優先）。"
                       " 來源：TWSE OpenAPI（法說會/股東會/除權息）。"}
    AUTO_PATH.write_text(
        json.dumps({**header, **acc}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：寫入 {total} 筆未來事件 → {AUTO_PATH}")
    for sid, evs in sorted(acc.items()):
        for e in evs:
            print(f"  {sid} {e['date']} {e['type']} {e['note']}")


if __name__ == "__main__":
    main()
