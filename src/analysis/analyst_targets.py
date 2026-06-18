"""投顧目標價 → 回推隱含本益比。

兩個來源：
1) 新聞擷取（best-effort）：近 N 天、具名券商、數字落在現價合理範圍，濾掉過期/別檔。
2) 知識庫投顧報告（高品質）：若 個股/<代號>_*/投顧報告/ 有 .txt/.md 且設了 GEMINI_KEY，
   用 Gemini 讀內文抓「目標價＋券商預估EPS」。

回推隱含PER = 目標價 ÷ 預估EPS。給低/中/高區間，並與歷史河流圖對照。
"""
from __future__ import annotations

import os
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

from src.data import gemini_client as gem
from src.data import news_sources

_TP_RE = re.compile(
    r"(?:目標價|上看|看到|上調至|調升至|上修至|喊上|喊到|調高至|上修)[^0-9元]{0,5}"
    r"([0-9][0-9,]{1,5})(?:\.[0-9]+)?\s*元"
)
_TP_BAD_PREFIX = ("EPS", "eps", "獲利", "賺", "營收", "股本")
_TP_COMPARE = ("贏過", "不只", "勝過", "超車", "打敗", "海放")
_NAMED_FIRMS = ["摩根士丹利", "大摩", "摩根大通", "小摩", "摩根", "高盛", "瑞銀", "UBS", "美林",
                "花旗", "野村", "瑞信", "麥格理", "里昂", "傑富瑞", "Jefferies", "匯豐", "星展",
                "巴克萊", "德意志", "凱基", "元大", "富邦", "群益", "中信", "第一金",
                "兆豐", "國泰", "永豐", "統一", "美銀"]

_DEFAULT_KB = r"G:\我的雲端硬碟\secondbrain\創作庫\光之國度自動代理人計畫\知識庫"


def _kb_dir() -> Path:
    return Path(os.environ.get("STOCKBRAIN_KB_DIR", _DEFAULT_KB))


def news_targets(sid: str, name: str | None, ref_price: float | None = None,
                 recent_days: int = 60) -> list[dict]:
    """從近期新聞擷取具名券商目標價。回 [{date,broker,target}]。"""
    try:
        df = news_sources.target_price_news(sid, name)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    since = (date.today() - timedelta(days=recent_days)).isoformat()
    lo = hi = None
    if ref_price:
        lo, hi = ref_price * 0.4, ref_price * 2.6
    out, seen = [], set()
    for _, r in df.iterrows():
        d = str(r.get("date", ""))[:10]
        if d and d < since:
            continue
        title = str(r.get("title", ""))
        if any(w in title for w in _TP_COMPARE):
            continue
        broker = next((b for b in _NAMED_FIRMS if b in title), None)
        if not broker:
            continue
        for m in _TP_RE.finditer(title):
            before = title[max(0, m.start() - 4):m.start()]
            if any(b in before for b in _TP_BAD_PREFIX):
                continue
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if v < 50 or (lo and not (lo <= v <= hi)):
                continue
            key = (broker, int(v))
            if key in seen:
                continue
            seen.add(key)
            out.append({"date": d, "broker": broker, "target": v})
    return out


def kb_report_targets(sid: str, name: str | None) -> list[dict]:
    """讀知識庫投顧報告內文，用 Gemini 抓目標價（高品質，需報告檔＋GEMINI_KEY）。"""
    if not gem.is_configured():
        return []
    base = _kb_dir() / "個股"
    if not base.exists():
        return []
    folder = next((d for d in base.iterdir() if d.is_dir() and d.name.split("_")[0] == sid), None)
    if not folder:
        return []
    texts = []
    for p in (folder / "投顧報告").rglob("*") if (folder / "投顧報告").exists() else []:
        if p.suffix.lower() in (".txt", ".md") and not p.name.startswith(("_放這裡", "_系統自動")):
            try:
                texts.append(p.read_text(encoding="utf-8", errors="ignore")[:3000])
            except Exception:
                pass
    if not texts:
        return []
    prompt = (
        f"以下是 {name}({sid}) 的投顧報告內文。請抽出每家券商的『目標價』與（若有）『預估EPS』，"
        f"只輸出每行一筆，格式：券商|目標價|預估EPS（沒有就留空），不要其他字。無法判斷就回 NONE。\n\n"
        + "\n---\n".join(texts)
    )
    try:
        resp = gem.generate(prompt)
    except Exception:
        return []
    out = []
    for line in resp.splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 2:
            try:
                tgt = float(re.sub(r"[^0-9.]", "", parts[1]))
            except ValueError:
                continue
            if tgt < 50:
                continue
            eps = None
            if len(parts) >= 3 and parts[2]:
                try:
                    eps = float(re.sub(r"[^0-9.]", "", parts[2]))
                except ValueError:
                    eps = None
            out.append({"date": "報告", "broker": parts[0][:10], "target": tgt, "eps": eps})
    return out


def summarize(sid: str, name: str | None, snap: dict, fwd_eps: float | None = None) -> dict | None:
    """彙整投顧目標價 + 回推隱含PER。查不到回 None。"""
    price = (snap.get("price", {}) or {}).get("close")
    kb = kb_report_targets(sid, name)
    news = news_targets(sid, name, price)
    targets = kb + news
    if not targets:
        return None
    vals = sorted(t["target"] for t in targets)
    lo, hi = vals[0], vals[-1]
    med = round(statistics.median(vals))
    out = {"n": len(targets), "lo": round(lo), "med": med, "hi": round(hi),
           "from_report": bool(kb), "samples": targets[:6]}
    if fwd_eps:
        out["implied_per"] = (round(lo / fwd_eps, 1), round(med / fwd_eps, 1), round(hi / fwd_eps, 1))
    if price:
        out["med_vs_price_pct"] = round((med / price - 1) * 100, 1)
    return out


def brief(sid: str, name: str | None, snap: dict, fwd_eps: float | None = None) -> str:
    s = summarize(sid, name, snap, fwd_eps)
    if not s:
        return ""
    src = "投顧報告" if s["from_report"] else "近期新聞"
    line = f"投顧目標價({src}, {s['n']}筆)：區間 {s['lo']}~{s['hi']}、中位 {s['med']}"
    if s.get("med_vs_price_pct") is not None:
        line += f"（中位比現價 {s['med_vs_price_pct']:+}%）"
    if s.get("implied_per"):
        ip = s["implied_per"]
        line += f"；回推隱含PER(用預估EPS) {ip[0]}/{ip[1]}/{ip[2]} 倍"
    return line
