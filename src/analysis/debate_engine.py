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
from datetime import date
from pathlib import Path

from src.analysis import fundamental_forecast
from src.analysis import valuation_bands
from src.data import finmind_client as fm
from src.data import gemini_client as gem
from src.data import macro_data
from src.data import news_sources

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


def load_expert_kb(stem: str | None, limit: int = 3500) -> str:
    """讀某位專家專屬的知識本：知識庫/專家知識/<stem>.md（培養單一專家用）。"""
    if not stem:
        return ""
    f = kb_dir() / "專家知識" / f"{stem}.md"
    if not f.exists():
        return ""
    try:
        return f.read_text(encoding="utf-8", errors="ignore").strip()[:limit]
    except Exception:
        return ""


def load_expert_kb_folder(folder: str, limit: int = 4500) -> str:
    """讀某資料夾下所有大師知識本（統合專家用）：知識庫/專家知識/<folder>/*.md。"""
    d = kb_dir() / "專家知識" / folder
    if not d.exists():
        return ""
    chunks, total = [], 0
    for p in sorted(d.glob("*.md")):
        try:
            t = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not t:
            continue
        chunks.append(f"【{p.stem} 的方法】\n{t}")
        total += len(t)
        if total > limit:
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


# --- 討論自動存檔 + 回讀（讓專家滾雪球變強）--------------------------------
def _archive_dir() -> Path:
    return kb_dir() / "_每日討論存檔"


def save_discussion(sid: str, name: str, transcript: list[dict]) -> str | None:
    """把本次討論存成 md：結論摘要放最前面，方便下次回讀。回存檔路徑。"""
    if not transcript:
        return None
    try:
        d = _archive_dir() / f"{sid}_{name}"
        d.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        closing = next((t["text"] for t in reversed(transcript) if t["name"] == "主持人"), "")
        lines = [f"# {today} {name}({sid}) 討論存檔", "", "## 結論摘要", closing, "", "## 完整討論", ""]
        for t in transcript:
            lines.append(f"### {t['emoji']} {t['name']}")
            lines.append(t["text"])
            lines.append("")
        path = d / f"{today}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def load_past_discussions(sid: str, limit: int = 2, max_chars: int = 1400) -> str:
    """讀這檔最近幾次的『結論摘要』，給專家回顧（對照當時看法對了沒）。查不到回空字串。"""
    root = _archive_dir()
    if not root.exists():
        return ""
    folder = next((p for p in root.iterdir() if p.is_dir() and p.name.split("_")[0] == sid), None)
    if folder is None:
        return ""
    files = sorted(folder.glob("*.md"), reverse=True)[:limit]
    chunks: list[str] = []
    for p in files:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        head = t.split("## 完整討論")[0].strip()  # 只取日期＋結論摘要
        if head:
            chunks.append(head)
    return "\n\n---\n\n".join(chunks)[:max_chars]


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
    lines = [
        f"標的：{name}({sid})　資料日 {p.get('date', '—')}",
        f"收盤 {p.get('close')}（漲跌 {p.get('change_pct')}%）",
        f"估值：PER {v.get('per')}｜PBR {v.get('pbr')}｜PEG {v.get('peg')}｜殖利率 {v.get('dividend_yield_pct')}%",
        f"基本面：EPS(近四季) {f.get('eps_ttm')}｜ROE {f.get('roe_ttm_pct')}%｜毛利率 {f.get('gross_margin_pct')}%｜淨利率 {f.get('net_margin_pct')}%｜三率三升 {tr_txt}",
        f"籌碼：外資20日 {c.get('foreign_net_20d_lots')} 張｜投信20日 {c.get('trust_net_20d_lots')} 張｜外資持股 {c.get('foreign_holding_pct')}%",
    ]
    vb = valuation_bands.brief(sid, snap, name)
    if vb:
        lines.append(vb)
    # 8步驟預估（附在 data_brief 尾部，供估算專家 / Gemini 引用）
    try:
        fc = fundamental_forecast.compute(sid)
        fc_txt = fundamental_forecast.summary(sid, name, fc)
        lines.append(fc_txt)
    except Exception:
        pass
    return "\n".join(lines)


# --- 專家陣容 ---------------------------------------------------------------
EXPERTS = [
    {"key": "host_open", "name": "主持人", "emoji": "🧑‍⚖️", "kind": "open",
     "role": "你是專家討論的主持人。用 1-2 句宣布今天討論的標的與目前股價，點出一個今天最值得吵的問題，然後請專家發言。"
             "若有『上次討論回顧』，**開場先用一句話對照**（例如：上次我們判斷○○，今天來看…），再進入今天主題。繁體中文。"},
    {"key": "fund", "name": "基本面專家", "emoji": "📊", "kind": "speak", "kb": "基本面專家",
     "role": "你是基本面與估值專家。只根據提供的財務/估值數據，依使用者的評分準則判斷這檔基本面強弱。"
             "**務必引用資料裡『本益比河流圖』的便宜/合理/昂貴價，明說現價落在哪一區**；電子/成長股以『用預估EPS』那組為主（向前看）。要引用具體數字。3-5 句，繁體中文。"},
    {"key": "forecast", "name": "EPS估算專家", "emoji": "🔢", "kind": "speak",
     "role": ("你是基本面估算專家，完全採用孫慶龍老師的財報魔法師方法論。"
              "核心公式：預估營收 = 去年全年營收 × (1 + 今年前N月累積年增率) → 預估EPS = 預估營收 × 稅後淨利率 ÷ 發行股數。"
              "孫老師強調：股價只是結果，未來獲利才是原因。要動態調整評價——每一季新財報出來就更新EPS預估，不能死抱舊數字。"
              "實戰案例思維：他以2026年鴻海為例，用前5月近3成年增率×8.1兆基期=10兆營收×2.88%淨利率÷140億股=EPS 20.54元。"
              "請用同樣邏輯對這檔股票試算，給出今明兩年EPS預估區間（樂觀/保守），並說明哪個假設最關鍵。"
              "4-6句，繁體中文，引用具體數字。"
              "再乘TTM稅後淨利率→預估稅後淨利，除以發行股數→預估EPS，最後乘近三年平均盈餘分配率→預估股利。"
              "你的任務是**直接引用試算結果**（已列在即時數據中），點出這個預估數字與現在市場預期或股價隱含的差距，"
              "指出最關鍵的上修/下修風險（例如下半年淡旺季差異、客戶集中度、匯率）。"
              "**不要重複其他專家講過的估值評論**，聚焦『盈餘能見度』與『預估EPS對比現股價的隱含本益比』。"
              "3-5 句，繁體中文，引用具體數字。")},
    {"key": "valuation", "name": "企業估值專家", "emoji": "💎", "kind": "speak",
     "role": (
         "你是企業估值專家，完全使用孫慶龍老師（財報魔法師）的價值投資體系。"
         "核心三準則：好公司 × 好價格 × 買低賣高。核心信念：股市不會天天過年，遇回檔才是百貨公司週年慶、火車進站的機會。\n"
         "**孫慶龍三價位框架**（最重要）：\n"
         "  - 便宜價 = 預估EPS × 11.5倍（跌到這裡要解定存買）\n"
         "  - 合理價 = 預估EPS × 15倍（正常持有區間）\n"
         "  - 昂貴價 = 預估EPS × 20倍以上（警覺，勿追）\n"
         "**實戰驗證用「挑女婿」四維度**：\n"
         "① 營收面 → P/S合不合理\n"
         "② 獲利面 → PER：現價落在便宜/合理/昂貴哪一區\n"
         "③ 資產面 → PBR：<1有資產保護，>3需強獲利撐\n"
         "④ 成長面 → PEG：<1成長被低估，>2溢價過高\n"
         "**孫老師警示**：若股價已漲到2027-2028年預估獲利，要特別謹慎，因為任何風吹草動都會大幅修正。\n"
         "給出明確結論：現價是『便宜值得佈局』/『合理可分批』/『昂貴追高會套』，並說出孫老師估算的便宜價在哪裡。"
         "5-7句，繁體中文，引用具體數字。"
     )},
    {"key": "hsu", "name": "徐黎芳專家", "emoji": "🐆", "kind": "speak", "kb": "籌碼分析師/徐黎芳",
     "role": "你是徐黎芳（賺豹女王）派的籌碼專家，完全用她的方法判讀：逆韭菜跟大戶、兩股勢力對抗（主力買散戶賣連2-3天）、融資成本線（站上＝動能啟動）、買賣家數差負值（大戶集中買）、異常現象。引用她的框架並結合提供的籌碼數據，給偏多/偏空判斷。2-4 句，繁體中文。"},
    {"key": "chip_synth", "name": "籌碼統合專家", "emoji": "🎯", "kind": "speak", "kb": "籌碼統合專家", "kb_folder": "籌碼分析師",
     "role": "你是籌碼統合專家，讀過所有籌碼大師（徐黎芳等）的方法。請綜合『各家方法＋即時籌碼數據（法人買賣超/外資持股/融資）』給整合判斷：目前偏多還偏空、最關鍵的訊號、各家是否一致或有矛盾。可講『徐黎芳會看X、數據顯示Y、綜合是Z』。2-5 句，繁體中文。"},
    {"key": "bear", "name": "風險空方", "emoji": "⚠️", "kind": "speak", "kb": "風險空方",
     "role": "你是風險與空方代表。任務是挑前面論點的毛病、指出最大風險（估值過高、景氣循環、單一客戶、政策、籌碼鬆動等）。犀利但只講事實與數據。2-4 句，繁體中文。"},
    {"key": "host_close", "name": "主持人", "emoji": "🧑‍⚖️", "kind": "close",
     "role": ("你是主持人，做最終總結。**開頭第一行務必是固定格式：「📌 <總分>分 <分級> ｜ <15字內一句話重點(含最大風險)>」**，方便手機推播擷取；接著再條列詳細結論。"
              "綜合前面討論（含消息面與交鋒回合），依使用者 SOP 的 100 分制（基本面40／籌碼25／技術20／題材15；"
              "技術與題材若資料不足，明講『資料不足、暫不評分』不要硬掰）給一個粗略總分與分級"
              "（80+ 強買／60-79 可買／40-59 觀察／<40 跳過）。**四項分數加總要等於總分，不要再額外加扣分**。"
              "分數只評個股體質；另外**獨立給一句『進場時機』判斷**——根據國際情勢專家講的總體/資金面，"
              "說現在大環境對買進是順風還是逆風（例如美股大型 IPO 吸金、外資撤離時，體質好也先等）。"
              "再點出最大風險一句、以及方才交鋒中誰的論點較站得住腳。"
              "最後務必加一句：『以上為公開資訊＋AI 推理，不是明牌；最終買賣由你自己按。』繁體中文，條列清楚。")},
]

# --- 🔥 交鋒回合：第一輪講完後，基本面 ↔ 風險空方 直接對嗆兩輪 -----------------
REBUT_FUND = {"key": "fund_rebut", "name": "基本面專家", "emoji": "📊", "kind": "speak",
    "role": ("你是基本面專家，現在進入【交鋒回合】。風險空方剛剛挑了你的毛病。"
             "請直接點名回應他：他哪一點你承認、哪一點你用具體財務/估值數字反駁回去。"
             "據理力爭、可以嗆回去，但只憑數據。2-3 句，繁體中文。")}
REBUT_BEAR = {"key": "bear_rebut", "name": "風險空方", "emoji": "⚠️", "kind": "speak",
    "role": ("你是風險空方，這是【交鋒回合】最後反擊。基本面專家剛回應了你，"
             "請抓住他論點裡最站不住腳的一點再追打一次，並重申這檔現在最該防的風險。"
             "犀利、只講數據與事實。2-3 句，繁體中文。")}


# --- 真腦：Gemini -----------------------------------------------------------
def _gemini_turn(expert: dict, brief: str, kb: dict, transcript: list[dict], past: str = "") -> str:
    convo = "\n".join(f"{t['name']}：{t['text']}" for t in transcript) or "（尚無發言）"
    ctx = kb.get("context", "")[:2500]
    stock_kb = kb.get("stock", "")[:2000]
    expert_kb = load_expert_kb(expert.get("kb"))
    if expert.get("kb_folder"):
        folder_kb = load_expert_kb_folder(expert["kb_folder"])
        if folder_kb:
            expert_kb = (expert_kb + "\n\n=== 各籌碼大師方法彙整 ===\n" + folder_kb).strip()
    past_block = (
        f"=== 上次討論回顧（對照當時看法對了沒、有何變化；沒有就忽略）===\n{past}\n\n"
        if past else ""
    )
    if transcript:  # 已有人發言 → 要求點名交鋒，營造辯論感
        speak = (
            f"請以「{expert['name']}」身分發言。"
            f"**第一句一定要點名回應前面至少一位專家**：同意就說「我認同○○專家的…，再補一點…」，"
            f"不同意就直接說「我不同意○○專家，因為數據顯示…」。可以據理力爭、互相打臉，"
            f"但只憑數據與事實，不要重複別人講過的內容。像真的在會議室裡辯論。"
        )
    else:  # 開場第一位
        speak = f"請以「{expert['name']}」身分發言："
    prompt = (
        f"{expert['role']}\n\n"
        f"=== 你的專業知識本（你的方法論，務必依此判讀；使用者持續在養你）===\n{expert_kb or '（尚未建立，用你的專業常識）'}\n\n"
        f"=== 使用者的投資紀律與脈絡（請依此立場，不要用通用常識）===\n{ctx or '（無）'}\n\n"
        f"=== 這檔的補充資料（投顧報告/使用者筆記）===\n{stock_kb or '（無）'}\n\n"
        f"{past_block}"
        f"=== 即時數據 ===\n{brief}\n\n"
        f"=== 目前討論記錄 ===\n{convo}\n\n"
        f"{speak}"
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
    _buy = isinstance(fn, (int, float)) and fn and fn > 0
    if k == "hsu":
        return (f"用徐黎芳的招看：要的是『主力買、散戶賣連 2-3 天』。目前外資 {fn} 張、投信 {tn} 張——"
                + ("法人偏買、方向對，再確認有沒有站上融資成本線（站上＝動能啟動）。" if _buy
                   else "主力沒明顯站買方，先別追，等籌碼轉、別當接刀的散戶。"))
    if k == "chip_synth":
        return (f"統合各家籌碼：外資20日 {fn} 張、投信 {tn} 張、外資持股 {c.get('foreign_holding_pct')}%。"
                + ("徐黎芳的『主力買散戶賣』成立、偏多；綜合判斷籌碼面偏正向。" if _buy
                   else "徐黎芳的『主力買散戶賣』還沒成立；綜合判斷籌碼面中性偏空，等訊號。")
                + "（真腦會讀全部大師方法＋更細數據）")
    if k == "bear":
        return f"我潑冷水：PER {per} 這個估值已經反映不少樂觀預期，一旦營收成長不如預期或國際利空，殺估值的空間不小。先確認你的 −10% 機械停損有設。"
    if k == "fund_rebut":
        return (f"我回應風險空方：估值貴我承認，但 PER {per} 是拿『成長』換的——EPS {eps}、ROE {roe}% 撐得住；"
                "只要三率還在升，殺估值頂多是短線。核心部位我不動。")
    if k == "bear_rebut":
        return (f"我再追一句：你講的成長都是『預期』，外資近 20 日提款 {fn} 張是『事實』。"
                "事實打臉預期時先保命——−10% 機械停損務必守，別把波段風險凹成長線套牢。")
    if k == "host_close":
        return ("【結論（示範）】\n"
                f"- 基本面：EPS {eps}、ROE {roe}%、三率三升{'✅' if tr else '❌' if tr is not None else '—'}\n"
                f"- 估值：PER {per}（{'偏貴' if isinstance(per,(int,float)) and per and per>18 else '合理'}）\n"
                f"- 籌碼：外資{fn}張/投信{tn}張\n"
                "- 粗略分級：可買區待回檔（示範分數，真腦會用 SOP 細算）\n"
                "- 最大風險：估值偏高，利空來時先殺估值\n"
                "- 以上為公開資訊＋AI 推理，不是明牌；最終買賣由你自己按。")
    return "（…）"


# --- 💎 企業估值專家：好公司×好價格×買低賣高，孫慶龍挑女婿多維度框架 ------
def _valuation_demo(expert: dict, name: str, sid: str, snap: dict) -> str:
    v = snap.get("valuation", {}) or {}
    f = snap.get("fundamentals", {}) or {}
    p = snap.get("price", {}) or {}
    per = v.get("per"); pbr = v.get("pbr"); peg = v.get("peg")
    div_y = v.get("dividend_yield_pct")
    close = p.get("close")
    lines = ["【企業估值 — 挑女婿框架交叉驗證（示範）】"]
    lines.append(f"② 本益比(PER): {per} 倍｜" + ("偏貴，追價需謹慎。" if isinstance(per,(int,float)) and per and per > 20 else "尚在合理區。"))
    lines.append(f"③ 股價淨值比(PBR): {pbr} 倍｜" + (">3 需強獲利支撐。" if isinstance(pbr,(int,float)) and pbr and pbr > 3 else "資產面尚可接受。"))
    lines.append(f"④ PEG: {peg}｜" + ("≤1 成長被低估。" if isinstance(peg,(int,float)) and peg and peg <= 1 else "成長溢價已反映。" if peg else "資料不足。"))
    # 存股357
    flags = []
    if isinstance(per,(int,float)) and per and per <= 15: flags.append("PER≤15✅")
    if isinstance(div_y,(int,float)) and div_y and div_y >= 5: flags.append("殖利率≥5%✅")
    if isinstance(pbr,(int,float)) and pbr and pbr <= 1.5: flags.append("PBR≤1.5✅")
    lines.append(f"⑤ 存股357: {', '.join(flags) if flags else '均未達標，非典型存股標的'}")
    lines.append("（示範模式，真腦 Gemini 會依所有數據給出完整多方法交叉驗證判斷）")
    return "\n".join(lines)


# --- 🎤 名人觀點專家：上網搜你追蹤的分析師對本檔的最新公開消息 --------------
PUNDIT = {"key": "pundit", "name": "名人觀點專家", "emoji": "🎤"}


def pundit_findings(name: str, analysts: list[str], per: int = 2) -> list[dict]:
    """對每位分析師搜「分析師名 + 股名」的公開新聞，回 [{analyst, items:[{date,title,link}]}]。"""
    res = []
    for a in analysts:
        items = []
        try:
            df = news_sources.google_news(f"{a} {name}", limit=12)
            if df is not None and not df.empty:
                for _, r in df.head(per).iterrows():
                    items.append({"date": str(r.get("date", ""))[:10],
                                  "title": str(r.get("title", "")),
                                  "link": r.get("link", "")})
        except Exception:
            pass
        res.append({"analyst": a, "items": items})
    return res


def _pundit_demo(findings: list[dict]) -> str:
    lines = ["我去翻了幾位你追蹤的分析師最近的公開消息："]
    for f in findings:
        if f["items"]:
            top = f["items"][0]
            lines.append(f"- {f['analyst']}：`{top['date']}` {top['title'][:50]}")
        else:
            lines.append(f"- {f['analyst']}：近期無公開評論")
    lines.append("（資料來自公開新聞，付費會員內容不含；示範模式不深入解讀，真腦會幫你整理觀點）")
    return "\n".join(lines)


def _pundit_gemini(findings: list[dict], name: str) -> str:
    blocks = []
    for f in findings:
        if f["items"]:
            its = "\n".join(f"   - {i['date']} {i['title']}" for i in f["items"])
            blocks.append(f"- {f['analyst']}:\n{its}")
        else:
            blocks.append(f"- {f['analyst']}: (查無公開資料)")
    data = "\n".join(blocks)
    prompt = (
        f"你是「名人觀點專家」。以下是從公開新聞搜到的、幾位分析師近期與 {name} 相關的報導標題。"
        f"請用繁體中文，逐位簡述『這位分析師最近對 {name} 或相關情勢的公開看法』，可引用標題日期。"
        f"查無資料者明說『近期無公開評論』。嚴禁杜撰，也不要把別檔內容硬套到本檔。整體 3-6 句。\n\n{data}"
    )
    return gem.generate(prompt)


# --- 📰 消息面專家：每次討論即時抓最新新聞 + 投顧/目標價動向 -----------------
NEWS = {"key": "news", "name": "消息面專家", "emoji": "📰"}


def news_findings(name: str, sid: str, recent_n: int = 6, tp_n: int = 4) -> dict:
    """即時抓該股最新新聞 + 投顧/目標價相關報導。回 {'recent':[...], 'analyst':[...]}。"""
    recent, analyst = [], []
    try:
        df = news_sources.get_news(sid, name, days=21)
        if df is not None and not df.empty:
            for _, r in df.head(recent_n).iterrows():
                recent.append({"date": str(r.get("date", ""))[:10],
                               "title": str(r.get("title", "")),
                               "source": str(r.get("source", ""))})
    except Exception:
        pass
    try:
        tp = news_sources.target_price_news(sid, name)
        if tp is not None and not tp.empty:
            for _, r in tp.head(tp_n).iterrows():
                analyst.append({"date": str(r.get("date", ""))[:10],
                                "title": str(r.get("title", ""))})
    except Exception:
        pass
    return {"recent": recent, "analyst": analyst}


def _news_demo(f: dict) -> str:
    lines = ["我掃了近三週的新聞與投顧動向："]
    if f["recent"]:
        lines.append("📰 最新消息：")
        for it in f["recent"][:4]:
            lines.append(f"- `{it['date']}` {it['title'][:50]}（{it['source']}）")
    else:
        lines.append("- 近期查無明顯新聞。")
    if f["analyst"]:
        lines.append("📑 投顧/目標價動向：")
        for it in f["analyst"][:3]:
            lines.append(f"- `{it['date']}` {it['title'][:50]}")
    lines.append("（示範模式只列標題，真腦會幫你濃縮成消息面利多/利空並判斷影響）")
    return "\n".join(lines)


def _news_gemini(f: dict, name: str) -> str:
    today = date.today().isoformat()
    recent = "\n".join(f"- {i['date']} {i['title']}（{i['source']}）" for i in f["recent"]) or "（近期無明顯新聞）"
    analyst = "\n".join(f"- {i['date']} {i['title']}" for i in f["analyst"]) or "（近期無明確目標價/評等報導）"
    prompt = (
        f"你是專家討論的「消息面專家」，負責開場後第一個提供情報。**今天是 {today}**，"
        f"以最新日期的報導為準；標題若說『待公布／即將』但日期已過，視為已發生、別照抄過期說法。"
        f"以下是 {name} 近三週的新聞標題與投顧/目標價相關報導（只有標題，沒有內文）。"
        f"請用繁體中文整理成消息面重點：①最新利多、利空各抓 1-2 點 ②投顧目標價或評等動向 "
        f"③有沒有可能改變基本面或籌碼判斷的大事，提醒後面的專家注意。"
        f"嚴禁杜撰，只能根據標題；標題沒提到的不要腦補。整體 3-5 句、條列清楚。\n\n"
        f"=== 最新新聞 ===\n{recent}\n\n=== 投顧/目標價 ===\n{analyst}"
    )
    return gem.generate(prompt)


# --- 🌍 國際情勢專家：由上而下，抓總經/國際資金面（資金排擠、利率、匯率、地緣）---
MACRO = {"key": "macro", "name": "國際情勢專家", "emoji": "🌍"}

# 固定掃這些總體＋國際面向；個股基本面再好，也擋不住大盤級的資金抽離。
_MACRO_QUERIES = [
    "台股 外資 資金 排擠",
    "美股 大型 IPO 吸金",
    "Fed 利率 決議",
    "台幣 匯率 外資",
    "美國 關稅 貿易戰",
    "地緣政治 台海",
    "中國 經濟 刺激政策",
    "輝達 NVIDIA 訂單",
    "美國 晶片 出口管制",
]


_MACRO_NEWS_CACHE: dict[str, tuple[float, list]] = {}


def macro_findings(name: str, per_query: int = 3, recent_days: int = 5) -> list[dict]:
    """抓總經/國際面新聞（與個股無關的大盤級事件）。同一輪排程快取 30 分鐘、不重複抓。"""
    import time
    hit = _MACRO_NEWS_CACHE.get("macro_news")
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    items = _macro_findings_impl(per_query, recent_days)
    _MACRO_NEWS_CACHE["macro_news"] = (time.time(), items)
    return items


def _macro_findings_impl(per_query: int = 3, recent_days: int = 5) -> list[dict]:
    seen, items = set(), []
    for q in _MACRO_QUERIES:
        try:
            df = news_sources.google_news(f"{q} when:{recent_days}d", limit=per_query * 2)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        for _, r in df.head(per_query).iterrows():
            title = str(r.get("title", "")).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            items.append({"date": str(r.get("date", ""))[:10], "title": title,
                          "source": str(r.get("source", ""))})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:8]


def _macro_demo(items: list[dict], hard: str = "") -> str:
    lines = ["我從上而下看總體與國際資金面（個股基本面好，也擋不住大盤抽資金）："]
    if hard:
        lines.append(hard)
    if items:
        lines.append("【近期總經/國際新聞】")
        for it in items[:5]:
            lines.append(f"- `{it['date']}` {it['title'][:50]}（{it['source']}）")
        lines.append("（示範模式只列數據與標題；真腦會判斷有沒有『資金排擠／利率／匯率／地緣』在抽走台股動能）")
    elif not hard:
        lines.append("- 近期未抓到明顯的國際資金排擠或總經利空訊號。")
    return "\n".join(lines)


def _macro_gemini(items: list[dict], name: str, hard: str = "") -> str:
    today = date.today().isoformat()
    data = "\n".join(f"- {i['date']} {i['title']}（{i['source']}）" for i in items) or "（近期無明顯總經/國際資金面新聞）"
    hard_block = (
        f"=== 即時硬數據（權威數值，判斷市場狀態時以此為準，優先於新聞標題）===\n{hard}\n\n"
        if hard else ""
    )
    prompt = (
        f"你是專家討論的「國際情勢專家」，負責【由上而下】的視角，補其他專家只看個股的盲點。"
        f"**今天是 {today}。** 下面同時給你『即時硬數據』與『新聞標題』。\n"
        f"⚠️ 鐵則：**硬數據是當前真實數值，最可信**；新聞只有標題、可能落後——"
        f"若標題說『待公布／即將／預期』但日期早於今天，那件事多半已發生，別照抄過期說法。\n"
        f"請用繁體中文、條列判斷：①全球風向 risk-on/off：綜合 DXY美元指數、標普/那指/道瓊、VIX、"
        f"美債殖利率與殖利率曲線(倒掛=衰退警訊)、黃金原油、亞股(日經/上證/恆生) "
        f"②半導體連動：輝達/超微/費半走勢與出口管制消息，對台積電供應鏈的意義 "
        f"③台股大盤結構：外資台指淨多空、融資券水位、是否近結算日 "
        f"④重要事件行事曆：點出最近的 CPI/輝達財報/結算日等前瞻風險 "
        f"⑤就算 {name} 基本面沒變，這些總體力量會不會壓股價、讓外資撤出 "
        f"⑥結尾一句『現在大環境順風還是逆風』。引用具體數字。6-9 句。\n\n"
        f"{hard_block}"
        f"=== 總經/國際資金面新聞（已過濾近 {len(items)} 則）===\n{data}"
    )
    return gem.generate(prompt)


# --- 🔢 基本面估算專家：8步驟法（孫慶龍）------------------------------------
_FC_CACHE: dict[str, tuple[float, dict]] = {}


def _compute_forecast(sid: str) -> dict:
    """計算8步驟估算，同一輪快取 30 分鐘。"""
    import time
    hit = _FC_CACHE.get(sid)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        result = fundamental_forecast.compute(sid)
    except Exception as e:
        result = {"errors": [f"計算失敗: {e}"]}
    _FC_CACHE[sid] = (time.time(), result)
    return result


def _forecast_demo(result: dict, name: str, sid: str) -> str:
    return fundamental_forecast.summary(sid, name, result)


def _forecast_gemini(result: dict, name: str, sid: str, snap: dict) -> str:
    fc_txt = fundamental_forecast.summary(sid, name, result)
    today = date.today().isoformat()
    p = (snap.get("price", {}) or {})
    close = p.get("close")
    # 計算隱含本益比（現價 / 預估EPS）
    est_eps = result.get("est_eps")
    implied_per_txt = ""
    if est_eps and close and est_eps > 0:
        implied_per = round(float(close) / est_eps, 1)
        implied_per_txt = f"（現價 {close} ÷ 預估EPS {est_eps} = 隱含本益比 {implied_per} 倍）"

    prompt = (
        f"你是「估算專家」，使用孫慶龍8步驟法推估今年盈餘。**今天是 {today}。**\n"
        f"以下是系統依公開財報自動試算的結果，數字請直接引用，不要自行加減：\n\n"
        f"{fc_txt}\n\n"
        f"{implied_per_txt}\n\n"
        f"請用繁體中文，3-5 句，**不要重複河流圖/估值區間**（那是基本面專家的工作），聚焦：\n"
        f"①直接說預估EPS是多少、預估股利是多少 ②這個預估隱含多少本益比、算便宜還是貴 "
        f"③指出最大上修/下修風險（如下半年淡旺季、客戶集中度、匯率、淨利率是否可維持） "
        f"④若數字算不出來（無資料），要說明原因，不要捏造。引用具體數字，精簡有力。"
    )
    return gem.generate(prompt)


# --- 主流程：generator，一位專家一則 ----------------------------------------
def run_debate(sid: str, name: str, snap: dict, brain: str = "demo",
               analysts: list[str] | None = None):
    """逐則 yield {'name','emoji','text'}。brain='demo'|'gemini'。
    流程：主持開場 → 📰消息面 → 基本面 → 籌碼 →〔🎤名人〕→ 風險空方 → 🔥交鋒(基本面↔空方) → 主持總結。
    analysts 非空 → 多插一位 🎤 名人觀點專家（上網搜這些人對本檔的最新公開解盤）。"""
    brief = data_brief(name, sid, snap)
    kb = load_knowledge(sid)
    by_key = {e["key"]: e for e in EXPERTS}

    # 建立發言順序：開場 → 消息面 → 國際情勢 → 基本面 → EPS估算 → 企業估值 → 籌碼 →〔名人〕→ 空方 → 交鋒 → 收尾
    order = [by_key["host_open"], NEWS, MACRO, by_key["fund"], by_key["forecast"], by_key["valuation"], by_key["chip"]]
    findings = None
    if analysts:
        findings = pundit_findings(name, analysts)
        order.append(PUNDIT)  # 名人觀點排在風險空方之前
    order += [by_key["bear"], REBUT_FUND, REBUT_BEAR, by_key["host_close"]]

    # 消息面 + 國際情勢 + 8步驟估算，每次都即時計算
    news_f = news_findings(name, sid)
    macro_f = macro_findings(name)
    macro_hard = macro_data.summary_lines()  # yfinance 即時行情 + FRED 美國總經
    past = load_past_discussions(sid)         # 回讀上次討論結論（滾雪球）
    fc_result = _compute_forecast(sid)        # 8步驟基本面試算

    transcript: list[dict] = []
    for expert in order:
        k = expert["key"]
        try:
            if k == "news":
                text = _news_gemini(news_f, name) if brain == "gemini" else _news_demo(news_f)
            elif k == "macro":
                text = _macro_gemini(macro_f, name, macro_hard) if brain == "gemini" else _macro_demo(macro_f, macro_hard)
            elif k == "forecast":
                text = _forecast_gemini(fc_result, name, sid, snap) if brain == "gemini" else _forecast_demo(fc_result, name, sid)
            elif k == "valuation":
                text = _gemini_turn(expert, brief, kb, transcript, past) if brain == "gemini" else _valuation_demo(expert, name, sid, snap)
            elif k == "pundit":
                text = _pundit_gemini(findings, name) if brain == "gemini" else _pundit_demo(findings)
            elif brain == "gemini":
                text = _gemini_turn(expert, brief, kb, transcript, past)
            else:
                text = _demo_turn(expert, name, sid, snap)
        except Exception as e:  # noqa: BLE001
            text = f"（{expert['name']} 發言失敗：{type(e).__name__}: {e}）"
        turn = {"name": expert["name"], "emoji": expert["emoji"], "text": text}
        transcript.append(turn)
        yield turn

    # 討論結束 → 自動存檔，下次回讀
    save_discussion(sid, name, transcript)
