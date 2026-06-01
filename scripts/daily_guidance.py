"""每日法說會雷達（本機排程版）。

掃「我的清單」每檔 → 偵測近期法說會新聞 → 抽 guidance → 寫成 Markdown 進 Obsidian vault。
排程：用 Windows 工作排程器每天收盤後跑一次（見 README / 安裝說明）。

vault 路徑可用環境變數 RADAR_VAULT_DIR 覆寫（換 Mac 時設定）。
"""
import datetime as dt
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import guidance as gd
from src.data import finmind_client as fm
from src.data import news_sources
from src.data import watchlist

VAULT_DIR = Path(os.environ.get("RADAR_VAULT_DIR", r"G:\我的雲端硬碟\stockbrain"))
OUT_DIR = VAULT_DIR / "法說會雷達"


def scan_one(sid: str, name: str | None):
    nm = name or fm.stock_name(sid) or sid
    # 法說會專搜 + 一般新聞合併
    import pandas as pd
    frames = []
    for q in (f"{nm} 法說會", f"{nm} {sid}"):
        try:
            g = news_sources.google_news(q, limit=30)
            if not g.empty:
                frames.append(g)
        except Exception:
            pass
    if not frames:
        return nm, {}
    news = pd.concat(frames, ignore_index=True).drop_duplicates(subset="title")
    return nm, gd.summarize(news)


def main():
    wl = watchlist.load()
    if not wl:
        print("清單是空的，沒東西可掃。")
        return
    today = dt.date.today().isoformat()
    lines = [f"# 📡 法說會雷達 {today}", "",
             "> 每日自動掃描「我的清單」，從新聞擷取法說會 guidance（best-effort）。", ""]
    found_any = False
    for it in wl:
        nm, s = scan_one(it["sid"], it.get("name"))
        head = f"## {nm}({it['sid']})"
        if not s or not s.get("evidence"):
            lines += [head, "- （近期無法說會 guidance 訊號）", ""]
            continue
        found_any = True
        rev, gm, cap = s.get("營收成長%"), s.get("毛利率%"), s.get("資本支出(億美元)")
        summary = "、".join(filter(None, [
            f"全年營收成長 ~{rev}%" if rev else None,
            f"毛利率 ~{gm}%" if gm else None,
            f"資本支出 ~{cap} 億美元" if cap else None,
        ]))
        lines += [head, f"**guidance 彙整：** {summary or '（數字未明確）'}", "", "佐證新聞："]
        for e in s["evidence"][:5]:
            tags = "、".join(filter(None, [
                f"營收+{e['營收成長%']}%" if e["營收成長%"] else None,
                f"毛利{e['毛利率%']}%" if e["毛利率%"] else None,
                f"capex{e['資本支出(億美元)']}億" if e["資本支出(億美元)"] else None,
            ]))
            lines.append(f"- {e['date']} [{tags}] {e['title']}")
        lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"法說會雷達_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已寫入：{out}")
    print("有抓到 guidance" if found_any else "今日清單內無明顯 guidance 訊號")


if __name__ == "__main__":
    main()
