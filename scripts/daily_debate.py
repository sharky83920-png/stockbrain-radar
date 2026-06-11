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
from src.data import gemini_client as gem
from src.data import watchlist
from src.data.snapshot import build_snapshot


def run_one(sid: str, name: str | None, brain: str) -> dict:
    """跑一檔討論，回 {sid,name,conclusion,ok}。各檔的完整存檔由 run_debate 內建處理。"""
    rsid, rname = de.resolve_stock(sid)
    rname = rname or name or sid
    try:
        snap = build_snapshot(rsid or sid)
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "name": rname, "conclusion": f"（撈不到數據：{type(e).__name__}）", "ok": False}
    turns = list(de.run_debate(rsid or sid, rname, snap, brain=brain))
    conclusion = next((t["text"] for t in reversed(turns) if t["name"] == "主持人"), "")
    return {"sid": rsid or sid, "name": rname, "conclusion": conclusion, "ok": bool(conclusion)}


def main() -> None:
    wl = watchlist.load()
    if not wl:
        print("清單是空的，沒東西可討論。")
        return
    brain = "gemini" if gem.is_configured() else "demo"
    today = dt.date.today().isoformat()
    print(f"[{today}] 用腦：{brain}，清單 {len(wl)} 檔")

    results = []
    for it in wl:
        r = run_one(it["sid"], it.get("name"), brain)
        results.append(r)
        print(f"  - {r['name']}({r['sid']}): {'✅' if r['ok'] else '⚠️'}")

    # 寫每日總結到知識庫（會同步到手機）
    lines = [f"# 🧠 每日專家討論總結 {today}", "",
             f"> 自動排程跑「我的清單」{len(wl)} 檔（腦：{brain}）。各檔完整討論存於同層 `<代號>_<名稱>/`。", ""]
    for r in results:
        lines += [f"## {r['name']}({r['sid']})", r["conclusion"] or "（無結論）", ""]
    out_dir = de.kb_dir() / "_每日討論存檔"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"_每日總結_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已寫入總結：{out}")


if __name__ == "__main__":
    main()
