"""專家辯論引擎（光之國度 / 請專家們討論）。

設計原則：
- 換腦不換身：brain="demo"（假腦，不花錢）/ "gemini"（真腦）。
- 一顆引擎兩個入口：網頁鈕 + 之後的工作排程器都呼叫 run_debate()。
- 讀資料：重用 Radar 的 snapshot（FinMind 準資料）+ 使用者知識庫（RAG）。
- 串流：run_debate() 是 generator，一位專家講完就 yield 一則，UI 可逐則顯示。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from src.data import finmind_client as fm
from src.data import gemini_client as gem

# --- 知識庫（RAG）路徑 ------------------------------------------------------
# 預設指向 secondbrain vault 的知識庫；換電腦磁碟代號不同 → 用環境變數 STOCKBRAIN_KB_DIR 覆寫。
_DEFAULT_KB = r"G:\我的雲端硬碟\secondbrain\創作庫\光之國度自動代理人計畫\知識庫"


def kb_dir() -> Path:
    return Path(os.environ.get("STOCKBRAIN_KB_DIR", _DEFAULT_KB))


def _read_md_under(folder: Path, limit_chars: int = 4000) -> str:
    """把資料夾下所有 .md/.txt 內容串起來（best-effort，控制長度）。"""
    if not folder.exists():
        return ""
    chunks: list[str] = []
    total = 0
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() not in (".md", ".txt"):
            continue
        if p.name.startswith("_放這裡") or p.name.startswith("_系統自動"):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not t:
            continue
        chunks.append(f"【{p.parent.name}/{p.name}】\n{t}")
        total += len(t)
        if total > limit_chars:
            break
    return "\n\n".join(chunks)


def load_knowledge(sid: str) -> dict[str, str]:
    """讀使用者脈絡 + 該股的投顧報告/筆記。回 {'context':..,'stock':..}。"""
    base = kb_dir()
    context = _read_md_under(base / "00_我的脈絡", limit_chars=3000)
    # 個股資料夾命名為 <代號>_<名稱>，用代號前綴比對
    stock_txt = ""
    stocks_root = base / "個股"
    if stocks_root.exists():
        for d in stocks_root.iterdir():
            if d.is_dir() and d.name.split("_")[0] == sid:
                stock_txt = _read_md_under(d, limit_chars=3000)
                break
    return {"context": context, "stock": stock_txt}


# --- 代號 / 中文名 解析 -----------------------------------------------------
def resolve_stock(query: str) -> tuple[str | None, str | None]:
    """輸入代號(2330)或中文名(台積電) → 回 (代號, 名稱)。查不到回 (None, None)。"""
    q = (query or "").strip()
    if not q:
        return None, None
    if re.fullmatch(r"\d{3,6}[A-Z]?", q):  # 看起來像代號
        return q, fm.stock_name(q) or q
    # 中文名 → 查 TaiwanStockInfo 全表
    try:
        info = fm.fetch("TaiwanStockInfo", max_age_days=30)
    except Exception:
        return None, None
    if info.empty or "stock_name" not in info.columns:
        return None, None
    exact = info[info["stock_name"] == q]
    hit = exact if not exact.empty else info[info["stock_name"].str.contains(q, na=False)]
    if hit.empty:
        return None, None
    row = hit.iloc[0]
    return str(row["stock_id"]), str(row["stock_name"])


# --- 把 snapshot 整理成精簡資料簡報 -----------------------------------------
def data_brief(name: str, sid: str, snap: dict) -> str:
    p = snap.get("price", {}) or {}
    f = snap.get("fundamentals", {}) or {}
    v = snap.get("valuation", {}) or {}
    c = snap.get("chips", {}) or {}
    tr = f.get("three_rates_rising")
    tr_txt = "是" if tr else ("否" if tr is not None else "—")
    return "\n".join([
        f"標的：{name}({sid})　資料日 {p.get('date', '—')}",
        f"收盤 {p.get('close')}（漲跌 {p.get('change_pct')}%）",
        f"估值：PER {v.get('per')}｜PBR {v.get('pbr')}｜PEG {v.get('peg')}｜殖利率 {v.get('dividend_yield_pct')}%",
        f"基本面：EPS(近四季) {f.get('eps_ttm')}｜ROE {f.get('roe_ttm_pct')}%｜毛利率 {f.get('gross_margin_pct')}%｜淨利率 {f.get('net_margin_pct')}%｜三率三升 {tr_txt}",
        f"籌碼：外資20日 {c.get('foreign_net_20d_lots')} 張｜投信20日 {c.get('trust_net_20d_lots')} 張｜外資持股 {c.get('foreign_holding_pct')}%",
    ])


# --- 專家陣容 ---------------------------------------------------------------
EXPERTS = [
    {"key": "host_open", "name": "主持人", "emoji": "🧑‍⚖️", "kind": "open",
     "role": "你是專家討論的主持人。用 1-2 句宣布今天討論的標的與目前股價，點出一個今天最值得吵的問題，然後請專家發言。繁體中文。"},
    {"key": "fund", "name": "基本面專家", "emoji": "📊", "kind": "speak",
     "role": "你是基本面與估值專家。只根據提供的財務/估值數據，依使用者的評分準則判斷這檔基本面強弱、估值便宜還貴。要引用具體數字。2-4 句，繁體中文。"},
    {"key": "chip", "name": "籌碼專家", "emoji": "🎯", "kind": "speak",
     "role": "你是籌碼面專家。只根據法人買賣超與外資持股數據，判斷主力近期偏多還偏空。要引用具體數字。2-4 句，繁體中文。"},
    {"key": "bear", "name": "風險空方", "emoji": "⚠️", "kind": "speak",
     "role": "你是風險與空方代表。任務是挑前面論點的毛病、指出最大風險（估值過高、景氣循環、單一客戶、政策、籌碼鬆動等）。犀利但只講事實與數據。2-4 句，繁體中文。"},
    {"key": "host_close", "name": "主持人", "emoji": "🧑‍⚖️", "kind": "close",
     "role": ("你是主持人，做最終總結。綜合前面討論，依使用者 SOP 的 100 分制（基本面40／籌碼25／技術20／題材15；"
              "技術與題材若資料不足，明講『資料不足、暫不評分』不要硬掰）給一個粗略總分與分級"
              "（80+ 強買／60-79 可買／40-59 觀察／<40 跳過）。再點出最大風險一句。"
              "最後務必加一句：『以上為公開資訊＋AI 推理，不是明牌；最終買賣由你自己按。』繁體中文，條列清楚。")},
]


# --- 真腦：Gemini -----------------------------------------------------------
def _gemini_turn(expert: dict, brief: str, kb: dict, transcript: list[dict]) -> str:
    convo = "\n".join(f"{t['name']}：{t['text']}" for t in transcript) or "（尚無發言）"
    ctx = kb.get("context", "")[:2500]
    stock_kb = kb.get("stock", "")[:2000]
    prompt = (
        f"{expert['role']}\n\n"
        f"=== 使用者的投資紀律與脈絡（請依此立場，不要用通用常識）===\n{ctx or '（無）'}\n\n"
        f"=== 這檔的補充資料（投顧報告/使用者筆記）===\n{stock_kb or '（無）'}\n\n"
        f"=== 即時數據 ===\n{brief}\n\n"
        f"=== 目前討論記錄 ===\n{convo}\n\n"
        f"請以「{expert['name']}」身分發言（不要重複別人講過的，可以反駁）："
    )
    return gem.generate(prompt)


# --- 假腦：示範用罐頭（讀真數據，但不呼叫 API、不花錢）----------------------
def _demo_turn(expert: dict, name: str, sid: str, snap: dict) -> str:
    f = snap.get("fundamentals", {}) or {}
    v = snap.get("valuation", {}) or {}
    c = snap.get("chips", {}) or {}
    p = snap.get("price", {}) or {}
    per = v.get("per"); eps = f.get("eps_ttm"); roe = f.get("roe_ttm_pct")
    tr = f.get("three_rates_rising")
    fn = c.get("foreign_net_20d_lots"); tn = c.get("trust_net_20d_lots")
    k = expert["key"]
    if k == "host_open":
        return f"今天討論 {name}({sid})，目前股價 {p.get('close')}（{p.get('change_pct')}%）。重點問題：現在這個價位，基本面撐得住估值嗎？請各位發言。"
    if k == "fund":
        msg = f"基本面看：EPS(近四季) {eps}、ROE {roe}%、三率三升{'成立' if tr else '不成立' if tr is not None else '資料不足'}。"
        msg += f"估值 PER {per} 倍，" + ("以歷史看不算便宜，要看成長能不能追上。" if isinstance(per, (int, float)) and per and per > 18 else "估值還在合理區。")
        return msg
    if k == "chip":
        return f"籌碼面：外資近20日 {fn} 張、投信 {tn} 張。" + (
            "法人偏買方，動能還在。" if (isinstance(fn, (int, float)) and fn and fn > 0) else "法人沒明顯站買方，追價要小心。")
    if k == "bear":
        return f"我潑冷水：PER {per} 這個估值已經反映不少樂觀預期，一旦營收成長不如預期或國際利空，殺估值的空間不小。先確認你的 −10% 機械停損有設。"
    if k == "host_close":
        return ("【結論（示範）】\n"
                f"- 基本面：EPS {eps}、ROE {roe}%、三率三升{'✅' if tr else '❌' if tr is not None else '—'}\n"
                f"- 估值：PER {per}（{'偏貴' if isinstance(per,(int,float)) and per and per>18 else '合理'}）\n"
                f"- 籌碼：外資{fn}張/投信{tn}張\n"
                "- 粗略分級：可買區待回檔（示範分數，真腦會用 SOP 細算）\n"
                "- 最大風險：估值偏高，利空來時先殺估值\n"
                "- 以上為公開資訊＋AI 推理，不是明牌；最終買賣由你自己按。")
    return "（…）"


# --- 主流程：generator，一位專家一則 ----------------------------------------
def run_debate(sid: str, name: str, snap: dict, brain: str = "demo"):
    """逐則 yield {'name','emoji','text'}。brain='demo'|'gemini'。"""
    brief = data_brief(name, sid, snap)
    kb = load_knowledge(sid)
    transcript: list[dict] = []
    for expert in EXPERTS:
        try:
            if brain == "gemini":
                text = _gemini_turn(expert, brief, kb, transcript)
            else:
                text = _demo_turn(expert, name, sid, snap)
        except Exception as e:  # noqa: BLE001
            text = f"（{expert['name']} 發言失敗：{type(e).__name__}: {e}）"
        turn = {"name": expert["name"], "emoji": expert["emoji"], "text": text}
        transcript.append(turn)
        yield turn
