"""每日專家討論（本機排程版）。

掃「我的清單」每檔 → 跑專家討論（真腦優先，否則假腦）→
① 各檔自動存進 知識庫/_每日討論存檔/（run_debate 內建，下次回讀滾雪球）
② 另寫一份「每日總結」md 到 vault，手機開 Obsidian/雲端硬碟就能看。

排程：Windows 工作排程器每天跑（見 README / 安裝說明）。
注意：用真腦會花一點 Gemini 費用（flash-lite 很便宜）；清單越多檔花越多。
"""
import datetime as dt
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import debate_engine as de
from src.analysis import screener
from src.data import gemini_client as gem
from src.data import inbox
from src.data import macro_data
from src.data import notify
from src.data import watchlist
from src.data.snapshot import build_snapshot


def _chips_brief(snap: dict) -> str:
    """籌碼一行：外資/投信20日買賣超＋融資增減。"""
    c = snap.get("chips", {}) or {}
    fn, tn, mc = c.get("foreign_net_20d_lots"), c.get("trust_net_20d_lots"), c.get("margin_change_lots")
    parts = []
    if isinstance(fn, (int, float)):
        parts.append(f"外資{fn:+,.0f}")
    if isinstance(tn, (int, float)):
        parts.append(f"投信{tn:+,.0f}")
    if not parts:
        return ""
    s = "／".join(parts) + "張(20日)"
    if isinstance(mc, (int, float)):
        s += f"，融資{'↓' if mc < 0 else '↑'}"
    return s


def run_one(sid: str, name: str | None, brain: str) -> dict:
    """跑一檔討論，回 {sid,name,conclusion,chips,ok}。各檔完整存檔由 run_debate 內建處理。"""
    rsid, rname = de.resolve_stock(sid)
    rname = rname or name or sid
    try:
        snap = build_snapshot(rsid or sid)
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "name": rname, "conclusion": f"（撈不到數據：{type(e).__name__}）", "chips": "", "ok": False}
    turns = list(de.run_debate(rsid or sid, rname, snap, brain=brain))
    conclusion = next((t["text"] for t in reversed(turns) if t["name"] == "主持人"), "")
    return {"sid": rsid or sid, "name": rname, "conclusion": conclusion,
            "chips": _chips_brief(snap), "ok": bool(conclusion)}


def write_screen_report(kb_dir, today: str) -> None:
    """跑選股雷達，把『分數高但還沒追蹤』的新標的寫進 vault。"""
    try:
        picks = screener.screen(top_n=10)
    except Exception as e:  # noqa: BLE001
        print(f"選股雷達失敗：{type(e).__name__}: {e}")
        return
    lines = [f"# 🔍 選股雷達 {today}", "",
             "> 拿你的 SOP 掃候選池，挑『分數高、但你還沒追蹤』的。"
             "分數=基本面40+籌碼25（技術/題材掃描階段資料不足、不計）。"
             "想追蹤就把代號丟進『想追蹤的股票.md』。", ""]
    if not picks:
        lines.append("（今日候選池沒有通過一票否決又夠高分的新標的。）")
    for r in picks:
        lines.append(f"## {r['name']}({r['sid']})　{r['score']}/{r['max']} 分")
        lines.append("- " + "；".join(r["reasons"]) if r["reasons"] else "- （無加分項）")
        lines.append("")
    out = kb_dir / "_每日討論存檔" / f"_選股雷達_{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已寫入選股雷達：{out}（{len(picks)} 檔）")
    return picks


def _digest_line(r: dict) -> str:
    """從結論抓「📌」那行做精簡推播；抓不到就取前 48 字。"""
    verdict = ""
    for ln in (r.get("conclusion") or "").splitlines():
        s = ln.strip().replace("*", "")
        if s.startswith("📌"):
            verdict = s[1:].strip()
            break
    if not verdict:
        verdict = (r.get("conclusion") or "").strip().replace("*", "").replace("\n", " ")[:48]
    line = f"• {r['name']}{r['sid']}｜{verdict}"
    if r.get("chips"):
        line += f"\n　🎯籌碼：{r['chips']}"
    return line


def main() -> None:
    # 先讀手機收件匣，把新加的股票併進清單
    try:
        for r in inbox.process_inbox():
            print(f"  收件匣：「{r['input']}」→ {r['status']}")
    except Exception as e:  # noqa: BLE001
        print(f"收件匣處理失敗：{type(e).__name__}: {e}")

    wl = watchlist.load()
    if not wl:
        print("清單是空的，沒東西可討論。")
        return
    brain = "gemini" if gem.is_configured() else "demo"
    today = dt.date.today().isoformat()
    print(f"[{today}] 用腦：{brain}，清單 {len(wl)} 檔")

    # ① 我的清單逐檔討論
    wl_results = []
    for it in wl:
        r = run_one(it["sid"], it.get("name"), brain)
        wl_results.append(r)
        print(f"  清單 - {r['name']}({r['sid']}): {'✅' if r['ok'] else '⚠️'}")

    # ② 選股雷達寫全表 + 取前 3 檔也丟去討論
    picks = write_screen_report(de.kb_dir(), today) or []
    pick_results = []
    for p in picks[:3]:
        r = run_one(p["sid"], p["name"], brain)
        r["score"], r["max"] = p["score"], p["max"]
        pick_results.append(r)
        print(f"  雷達 - {r['name']}({r['sid']}): {'✅' if r['ok'] else '⚠️'}（{p['score']}/{p['max']}）")

    # 寫每日總結（兩組完整結論）到 vault
    lines = [f"# 🧠 每日專家討論總結 {today}", "", f"> 腦：{brain}。各檔完整討論存於同層 `<代號>_<名稱>/`。", "",
             "## ⭐ 我的清單", ""]
    for r in wl_results:
        lines += [f"### {r['name']}({r['sid']})", r["conclusion"] or "（無結論）", ""]
    lines += ["## 🔍 你可能會喜歡（選股雷達挑＋已討論）", ""]
    for r in pick_results:
        lines += [f"### {r['name']}({r['sid']})　雷達分 {r.get('score')}/{r.get('max')}", r["conclusion"] or "（無結論）", ""]
    out = de.kb_dir() / "_每日討論存檔" / f"_每日總結_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已寫入總結：{out}")

    # ③ 組精簡摘要，推播到手機
    digest = [f"🧠 光之國度 {today} 摘要", macro_data.headline(), "", "⭐ 我的清單"]
    digest += [_digest_line(r) for r in wl_results]
    if pick_results:
        digest += ["", "🔍 你可能會喜歡（雷達挑＋已討論）"]
        digest += [_digest_line(r) for r in pick_results]
    digest += ["", f"📂 全文：知識庫/_每日討論存檔/_每日總結_{today}.md"]
    ok, msg = notify.send("\n".join(digest))
    print(f"推播：{'✅ 已推到 Telegram' if ok else '⚠️ 未推（' + msg + '）'}")


if __name__ == "__main__":
    main()
