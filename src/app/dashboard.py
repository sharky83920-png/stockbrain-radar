"""StockBrain Radar — 個股研究 Dashboard (Streamlit)。

啟動：streamlit run src/app/dashboard.py
"""
import re
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.analysis import debate_engine
from src.analysis import eps_model
from src.analysis import guidance as guidance_mod
from src.analysis import industry as industry_mod
from src.analysis import news_digest
from src.analysis.valuation import pe_band
from src.data import finmind_client as fm
from src.data import gemini_client as gem
from src.data import analysts as analysts_mod
from src.data import news_sources
from src.data import watchlist
from src.data.snapshot import build_snapshot

# 投顧/法人相關新聞的過濾關鍵字（MoneyDJ 免費研究報告區已停更至 2011，改用新聞過濾）
ANALYST_KEYWORDS = [
    "目標價", "評等", "調升", "調降", "上修", "下修", "升評", "降評", "外資", "投顧",
    "加碼", "減碼", "買進", "賣出", "中立", "看好", "出具", "報告", "喊", "上調", "下調",
    "大摩", "小摩", "摩根", "高盛", "瑞銀", "美林", "花旗", "野村", "瑞信", "麥格理",
]

st.set_page_config(page_title="StockBrain Radar", page_icon="📡", layout="wide")

# 名詞解釋（滑鼠移到 ? 會顯示）
HELP = {
    "per": "本益比 PER（Price/Earnings）= 股價 ÷ 每股盈餘。市場願意為每 1 元獲利付多少錢，越高代表估值越貴。",
    "pbr": "股價淨值比 PBR（Price/Book）= 股價 ÷ 每股淨值。<1 代表股價低於帳面價值。",
    "peg": "本益成長比 PEG = 本益比 ÷ EPS年增率(%)。成長股看 PEG：<1 偏便宜、1~2 合理、>2 偏貴。",
    "roe": "股東權益報酬率 ROE（Return on Equity）= 稅後淨利 ÷ 股東權益。代表用股東的錢賺錢的效率，>15% 算優秀。此為近四季(TTM)估算。",
    "eps_ttm": "每股盈餘 EPS（Earnings Per Share）近四季加總（TTM＝Trailing Twelve Months）。",
    "gross": "毛利率 = 毛利 ÷ 營收。反映產品本身的賺錢能力。",
    "op": "營業利益率 = 營業利益 ÷ 營收。扣掉營業費用後的本業獲利能力。",
    "net": "淨利率 = 稅後淨利 ÷ 營收。最終獲利能力。毛利率/營益率/淨利率三者同步上升＝『三率三升』，是基本面轉強的訊號。",
    "debt": "負債比 = 總負債 ÷ 總資產。<60% 較安全。",
    "target": "分析師目標價：免費資料源沒有結構化的各券商目標價（屬付費資料），此處以程式從近期新聞標題擷取『目標價/上看 ___ 元』，屬 best-effort，量取決於新聞多寡（填 FinMind token 會更多）。",
    "foreign_net": "外資（外國機構投資人）近 N 個交易日買進張數減賣出張數。正=買超，負=賣超。",
    "trust_net": "投信（國內投資信託／基金）近 N 個交易日淨買賣張數。投信動向偏中線、較敏感。",
    "foreign_hold": "外資持股比例 = 外資持有股數 ÷ 總發行股數。",
    "margin": "融資餘額：投資人借錢買股的未償還張數。過高代表散戶熱情、上漲動能可能耗盡。",
    "yield_ttm": "近一年殖利率 = 近一年實際配發現金股利加總 ÷ 目前股價。",
    "yield_fwd": "年化殖利率（預估）= 最近一次現金股利 × 一年配發次數 ÷ 目前股價。屬前瞻性預估，非保證。",
    "river": "本益比河流圖：彩色帶＝各本益比倍數 ×（近四季EPS）對應的股價。黑線（收盤價）落在低帶＝便宜、落在高帶＝貴。EPS 以季底估算，故換季時帶會跳動。",
}


@st.cache_data(ttl=3600)
def _snapshot(sid: str):
    return build_snapshot(sid)


@st.cache_data(ttl=3600)
def _inst(sid: str):
    return fm.institutional_investors(sid, days=45).sort_values("date")


@st.cache_data(ttl=3600)
def _pe_band(sid: str):
    return pe_band(sid)


@st.cache_data(ttl=86400)
def _name(sid: str):
    return fm.stock_name(sid)


@st.cache_data(ttl=1800)
def _mini(sid: str):
    """清單比較總表用的精簡快照。"""
    s = _snapshot(sid)
    p, c, f, v = (s.get(k, {}) for k in ("price", "chips", "fundamentals", "valuation"))
    tr = "—"
    if isinstance(f, dict) and "three_rates_rising" in f:
        tr = "✅" if f["three_rates_rising"] else "❌"
    return {
        "代號": sid,
        "名稱": _name(sid) or sid,
        "收盤": p.get("close") if isinstance(p, dict) else None,
        "漲跌%": p.get("change_pct") if isinstance(p, dict) else None,
        "PER": v.get("per") if isinstance(v, dict) else None,
        "外資20日(張)": c.get("foreign_net_20d_lots") if isinstance(c, dict) else None,
        "投信20日(張)": c.get("trust_net_20d_lots") if isinstance(c, dict) else None,
        "三率三升": tr,
    }


@st.cache_data(ttl=1800)
def _news(sid: str):
    return news_sources.get_news(sid, _name(sid), days=21)


@st.cache_data(ttl=3600)
def _eps_fund(sid: str):
    return eps_model.fundamentals_ttm(sid)


@st.cache_data(ttl=3600)
def _pe_band3(sid: str, years: int = 3):
    from src.analysis.valuation import pe_band
    return pe_band(sid, years=years, percentiles=(20, 50, 80))


_GM_PCT = re.compile(r"毛利率[^0-9]{0,8}(\d{1,2}(?:\.\d)?)\s*%")


@st.cache_data(ttl=3600)
def _gm_news(sid: str):
    """擷取新聞中提到的毛利率（給 EPS 推估器設定拉桿參考）。"""
    import pandas as _pd
    nm = _name(sid) or sid
    frames = []
    for q in (f"{nm} 毛利率", f"{nm} 毛利率 外資", f"{nm} 法說 毛利率"):
        try:
            g = news_sources.google_news(q, limit=20)
            if not g.empty:
                frames.append(g)
        except Exception:
            pass
    if not frames:
        return []
    nz = _pd.concat(frames, ignore_index=True).drop_duplicates(subset="title")
    rows = []
    for _, r in nz.iterrows():
        t = str(r["title"])
        if "毛利率" not in t:
            continue
        m = _GM_PCT.search(t)
        rows.append({"date": str(r["date"])[:10], "毛利率%": m.group(1) if m else "—",
                     "title": t, "link": r.get("link", "")})
    # 有數字的優先、再依日期新→舊
    rows.sort(key=lambda x: (x["毛利率%"] == "—", ), )
    return rows[:8]


@st.cache_data(ttl=3600)
def _guidance(sid: str):
    import pandas as _pd
    nm = _name(sid) or sid
    frames = []
    for q in (f"{nm} 法說會", f"{nm} {sid}"):
        try:
            g = news_sources.google_news(q, limit=30)
            if not g.empty:
                frames.append(g)
        except Exception:
            pass
    if not frames:
        return {}
    news = _pd.concat(frames, ignore_index=True).drop_duplicates(subset="title")
    return guidance_mod.summarize(news)


@st.cache_data(ttl=1800)
def _tp_news(sid: str):
    """目標價專用新聞（專搜 + 一般合併），給目標價擷取用。"""
    import pandas as _pd
    a = news_sources.target_price_news(sid, _name(sid))
    b = _news(sid)
    frames = [d for d in (a, b) if d is not None and not d.empty]
    if not frames:
        return _pd.DataFrame()
    return _pd.concat(frames, ignore_index=True).drop_duplicates(subset="title")


# 嚴格擷取：觸發詞 + （5字內）數字 + 「元」。避免抓到年份(2027)、EPS(426元)等。
_TP_RE = re.compile(
    r"(?:目標價|上看|看到|上調至|調升至|上修至|喊上|喊到|調高至|上修)[^0-9元]{0,5}"
    r"([0-9][0-9,]{1,5})(?:\.[0-9]+)?\s*元"
)
# 數字前若緊接這些字 → 不是目標價（是 EPS/獲利等）
_TP_BAD_PREFIX = ("EPS", "eps", "獲利", "賺", "營收", "股本")
# 出現這些比較語氣 → 標題在講「別檔」打敗本檔，數字多半是別檔的
_TP_COMPARE = ("贏過", "不只", "勝過", "超車", "打敗", "海放")
# 只認「具名」的券商/機構——不含「外資/投信/法人/分析師」這種泛稱，也不採用媒體名
_NAMED_FIRMS = ["摩根士丹利", "大摩", "摩根大通", "小摩", "摩根", "高盛", "瑞銀", "UBS", "美林",
                "花旗", "野村", "瑞信", "麥格理", "里昂", "傑富瑞", "Jefferies", "匯豐", "星展",
                "巴克萊", "德意志", "Factset", "凱基", "元大", "富邦", "群益", "中信", "第一金",
                "兆豐", "國泰", "永豐", "統一", "美銀", "杜金龍"]


def _extract_target_prices(news_df, ref_price=None):
    lo = hi = None
    if ref_price:
        lo, hi = ref_price * 0.4, ref_price * 2.6  # 合理區間，濾掉同篇其他個股的目標價
    rows = []
    seen = set()
    for _, r in news_df.iterrows():
        title = str(r["title"])
        if any(w in title for w in _TP_COMPARE):  # 比較語氣 → 在講別檔，跳過
            continue
        vals = []
        for m in _TP_RE.finditer(title):
            before = title[max(0, m.start() - 4):m.start()]
            if any(b in before for b in _TP_BAD_PREFIX):  # 數字前是 EPS/獲利 → 跳
                continue
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if v < 50:  # 目標價通常 ≥ 50
                continue
            if lo and not (lo <= v <= hi):
                continue
            vals.append(str(int(v)))
        if not vals:
            continue
        broker = next((b for b in _NAMED_FIRMS if b in title), None)
        if not broker:
            continue  # 沒有明確具名券商/機構 → 不顯示（符合「要明確名稱」的要求）
        price_str = "、".join(sorted(set(vals), key=lambda x: float(x)))
        key = (broker, price_str)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "date": str(r["date"])[:10],
            "來源/券商": broker,
            "目標價": price_str,
            "title": title,
            "link": r["link"],
        })
    return rows


def _metric(col, label, value, suffix="", help_=None):
    txt = "—" if value is None else f"{value}{suffix}"
    col.metric(label, txt, help=help_)


# --- Sidebar ---------------------------------------------------------------
st.sidebar.title("📡 StockBrain Radar")
st.session_state.setdefault("sid_input", "2330")
sid = st.sidebar.text_input("股票代號（如 2330）", key="sid_input").strip()
st.sidebar.caption("資料來源：FinMind / Google News。當日快取，僅供個人研究。")


def _select_sid(s):
    st.session_state.sid_input = s


def _remove_sid(s):
    watchlist.remove(s)


def _add_current(s, nm):
    watchlist.add(s, nm)


def _remove_analyst(n):
    analysts_mod.remove(n)


def _add_analyst_cb():
    n = st.session_state.get("new_analyst", "").strip()
    if n:
        analysts_mod.add(n)
        st.session_state["new_analyst"] = ""


# 我的清單（存 Obsidian vault，跨機同步）
st.sidebar.divider()
st.sidebar.subheader("⭐ 我的清單")
_wl = watchlist.load()
if _wl:
    for _it in _wl:
        c1, c2 = st.sidebar.columns([4, 1])
        c1.button(f"{_it['name']}({_it['sid']})", key=f"wl_{_it['sid']}",
                  width="stretch", on_click=_select_sid, args=(_it["sid"],))
        c2.button("✕", key=f"rm_{_it['sid']}", on_click=_remove_sid, args=(_it["sid"],))
else:
    st.sidebar.caption("還沒有收藏，下方可加入。")

if sid:
    if watchlist.contains(sid):
        st.sidebar.caption(f"✓ {sid} 已在清單")
    else:
        st.sidebar.button(f"⭐ 加入 {sid}", key="add_cur",
                          on_click=_add_current, args=(sid, _name(sid)))

# 🎤 我的分析師（名人觀點，存 vault 跨機同步）
st.sidebar.divider()
st.sidebar.subheader("🎤 我的分析師")
st.sidebar.caption("討論時可勾「加入名人觀點」，請他們的最新公開解盤進場。")
for _a in analysts_mod.load():
    ca, cb = st.sidebar.columns([4, 1])
    ca.caption(_a["name"])
    cb.button("✕", key=f"rma_{_a['name']}", on_click=_remove_analyst, args=(_a["name"],))
st.sidebar.text_input("新增分析師（姓名/暱稱）", key="new_analyst")
st.sidebar.button("＋ 新增分析師", key="add_analyst", on_click=_add_analyst_cb)

if not sid:
    st.info("← 在左側輸入股票代號")
    st.stop()

snap = _snapshot(sid)
price = snap.get("price", {})
chips = snap.get("chips", {})
fund = snap.get("fundamentals", {})
val = snap.get("valuation", {})

# --- Header ----------------------------------------------------------------
_nm = _name(sid)
st.title(f"{_nm}({sid}) 個股研究" if _nm else f"{sid} 個股研究")
if isinstance(price, dict) and "close" in price:
    c1, c2, c3, c4, c5 = st.columns(5)
    _metric(c1, "收盤價", price.get("close"))
    delta = price.get("change_pct")
    # 台股慣例：上漲紅、下跌綠 → delta_color="inverse"（Streamlit 預設是美股的漲綠跌紅）
    c2.metric("漲跌幅", f"{price.get('change')}", f"{delta}%" if delta is not None else None,
              delta_color="inverse")
    _metric(c3, "本益比 PER", val.get("per") if isinstance(val, dict) else None, help_=HELP["per"])
    _metric(c4, "本益成長比 PEG", val.get("peg") if isinstance(val, dict) else None, help_=HELP["peg"])
    _metric(c5, "ROE 股東權益報酬率(近四季)", fund.get("roe_ttm_pct") if isinstance(fund, dict) else None, "%", help_=HELP["roe"])
    st.caption(f"資料日：{price.get('date')}　成交量：{price.get('volume_lots'):,} 張")
else:
    st.error(f"查無 {sid} 的價格資料，請確認代號。")

# 我的清單比較總表
if _wl:
    with st.expander(f"📋 我的清單比較總表（{len(_wl)} 檔）", expanded=False):
        try:
            st.dataframe(pd.DataFrame([_mini(i["sid"]) for i in _wl]),
                         hide_index=True, width="stretch")
        except Exception as e:  # noqa: BLE001
            st.caption(f"比較總表載入中或部分失敗：{e}")

tab_debate, tab_chip, tab_fund, tab_val, tab_news, tab_report, tab_industry = st.tabs(
    ["🧠 請專家們討論", "🎯 籌碼面", "📊 基本面", "💰 估值", "📰 相關新聞", "📑 投顧動向", "🏭 產業/供應鏈"]
)

# --- 🧠 請專家們討論 --------------------------------------------------------
with tab_debate:
    st.markdown("#### 🧠 請專家們討論")
    st.caption("輸入代號/中文名，專家即時抓『最新數據＋個股新聞＋投顧動向＋🌍國際資金面＋你的知識庫』，互相點名辯論、交鋒兩輪後給結論與進場時機。")
    dc1, dc2 = st.columns([3, 1])
    dq = dc1.text_input("股票代號或中文名稱（如 2330 或 台積電）", value=sid, key="debate_q").strip()
    demo_force = st.checkbox(
        "示範模式（假腦，不花錢）", value=not gem.is_configured(),
        help="勾選＝用罐頭發言示範流程、不呼叫 API、不花錢。取消＝用 Gemini 真腦（需在 .env 設好 GEMINI_KEY）。",
    )
    _al_names = analysts_mod.names()
    include_pundits = st.checkbox(
        f"🎤 加入名人觀點（上網搜 {len(_al_names)} 位分析師對本檔的最新公開解盤）",
        value=False,
        help="多一位『名人觀點專家』，用 Google News 搜你左側『我的分析師』清單對這檔的近期公開報導帶進討論。"
             "⚠️ 付費會員/訂閱內容搜不到（要自己貼進知識庫）。",
    )
    run_debate_btn = dc2.button("🚀 請專家們討論", width="stretch")
    if run_debate_btn:
        rsid, rname = debate_engine.resolve_stock(dq)
        if not rsid:
            st.error(f"查不到「{dq}」，請確認代號或中文名稱。")
        else:
            brain = "demo" if demo_force else "gemini"
            analysts_arg = _al_names if include_pundits else None
            _pundit_tag = f"　｜　🎤 名人觀點：{'、'.join(_al_names)}" if analysts_arg else ""
            st.info(f"討論標的：**{rname}({rsid})**　｜　腦：{'🧪 假腦（示範）' if brain == 'demo' else '🤖 Gemini'}{_pundit_tag}")
            try:
                dsnap = _snapshot(rsid)
            except Exception as e:  # noqa: BLE001
                st.error(f"撈不到 {rsid} 的數據：{type(e).__name__}: {e}")
                dsnap = None
            if dsnap:
                with st.spinner("專家討論中…"):
                    for turn in debate_engine.run_debate(rsid, rname, dsnap, brain=brain, analysts=analysts_arg):
                        with st.chat_message("assistant"):
                            st.markdown(f"{turn['emoji']} **{turn['name']}**\n\n{turn['text']}")
                st.success("討論結束，已自動存進知識庫 `_每日討論存檔/`，下次討論同一檔專家會先回顧。下一步可加：工作排程器定時跑 ＋ 推播到手機。")
    st.caption("⚠️ 公開資訊＋AI 推理，非投資建議。知識庫路徑可用環境變數 STOCKBRAIN_KB_DIR 覆寫。")


def _ai_summary_block(news_df, key_suffix):
    """共用：免金鑰重點整理（永遠顯示）+ Gemini 深度摘要（有 key 才有）。"""
    with st.expander("📋 重點整理（免 AI，依主題自動分類）", expanded=True):
        st.markdown(news_digest.digest(news_df))
    if gem.is_configured():
        if st.button("🤖 用 AI 生成深度摘要", key=f"ai_{key_suffix}"):
            with st.spinner("Gemini 摘要中…"):
                try:
                    st.success(gem.summarize_news(list(news_df["title"]), sid))
                except Exception as e:  # noqa: BLE001
                    st.error(f"摘要失敗：{type(e).__name__}: {e}")
    else:
        st.caption("🤖 AI 深度摘要：在 `.env` 填 `GEMINI_KEY`（與 GAS 晨報同一把）並重啟 dashboard 後解鎖。")

# --- 籌碼面 ----------------------------------------------------------------
with tab_chip:
    if isinstance(chips, dict) and "error" not in chips:
        a, b, c, d = st.columns(4)
        _metric(a, f"外資淨買賣（近{chips.get('window_days','?')}日）", chips.get("foreign_net_20d_lots"), " 張", help_=HELP["foreign_net"])
        _metric(b, "投信淨買賣（同期）", chips.get("trust_net_20d_lots"), " 張", help_=HELP["trust_net"])
        _metric(c, "外資持股比例", chips.get("foreign_holding_pct"), "%", help_=HELP["foreign_hold"])
        _metric(d, "融資餘額", f"{chips.get('margin_balance_lots'):,}" if chips.get("margin_balance_lots") is not None else None, " 張",
                help_=HELP["margin"] + f"（近45日變化 {chips.get('margin_change_lots')} 張）")
        st.divider()
        inst = _inst(sid)
        if not inst.empty:
            inst = inst.copy()
            inst["淨買賣（張）"] = (inst["buy"] - inst["sell"]) / 1000.0
            name_map = {"Foreign_Investor": "外資", "Investment_Trust": "投信",
                        "Dealer_self": "自營商（自行買賣）", "Dealer_Hedging": "自營商（避險）",
                        "Foreign_Dealer_Self": "外資自營"}
            inst["法人"] = inst["name"].map(name_map).fillna(inst["name"])
            keep = inst[inst["法人"].isin(["外資", "投信"])]
            fig = px.bar(keep, x="date", y="淨買賣（張）", color="法人", barmode="group",
                         title="三大法人每日淨買賣（外資 vs 投信）")
            fig.update_layout(xaxis_title="日期")
            st.plotly_chart(fig, width="stretch")
    else:
        st.warning(f"籌碼資料讀取問題：{chips.get('error') if isinstance(chips, dict) else chips}")

# --- 基本面 ----------------------------------------------------------------
with tab_fund:
    if isinstance(fund, dict) and "error" not in fund:
        a, b, c, d, e = st.columns(5)
        _metric(a, "毛利率", fund.get("gross_margin_pct"), "%", help_=HELP["gross"])
        _metric(b, "營業利益率", fund.get("operating_margin_pct"), "%", help_=HELP["op"])
        _metric(c, "淨利率", fund.get("net_margin_pct"), "%", help_=HELP["net"])
        _metric(d, "負債比", fund.get("debt_ratio_pct"), "%", help_=HELP["debt"])
        _metric(e, "每股盈餘 EPS（近四季）", fund.get("eps_ttm"), help_=HELP["eps_ttm"])
        st.caption(f"最新財報季：{fund.get('latest_quarter')}　EPS 年增率（與去年同季比）：{fund.get('eps_yoy_pct')}%")

        # 三率三升判斷
        if "three_rates_rising" in fund:
            detail = fund.get("three_rates_detail", {})
            def _ud(k, label):
                return f"{label}{'↑' if detail.get(k) else '↓/持平'}"
            tag = "　".join([_ud("gross", "毛利率"), _ud("op", "營益率"), _ud("net", "淨利率")])
            if fund["three_rates_rising"]:
                st.success(f"✅ **三率三升**（最新季 vs 前一季）：{tag}", icon="✅")
            else:
                st.warning(f"⚠️ 非三率三升（最新季 vs 前一季）：{tag}", icon="⚠️")

        # 三率趨勢圖
        ms = fund.get("margins_series") or []
        if len(ms) >= 2:
            mdf = pd.DataFrame(ms).rename(columns={"gross": "毛利率", "op": "營業利益率", "net": "淨利率"})
            long = mdf.melt(id_vars="q", value_vars=["毛利率", "營業利益率", "淨利率"],
                            var_name="指標", value_name="百分比")
            fig = px.line(long, x="q", y="百分比", color="指標", markers=True,
                          title="三率趨勢（近五季，%）")
            fig.update_layout(xaxis_title="財報季", yaxis_title="%")
            st.plotly_chart(fig, width="stretch")
        st.divider()
        col1, col2 = st.columns(2)
        rev = fund.get("revenue_yoy_recent") or []
        if rev:
            rdf = pd.DataFrame(rev)
            fig = px.bar(rdf, x="month", y="yoy_pct", title="月營收年增率 YoY（%）", text="yoy_pct")
            fig.update_layout(xaxis_title="月份", yaxis_title="年增率 %")
            col1.plotly_chart(fig, width="stretch")
        eps = fund.get("eps_recent") or []
        if eps:
            edf = pd.DataFrame(eps)
            fig = px.bar(edf, x="q", y="eps", title="近四季每股盈餘 EPS（元）", text="eps")
            fig.update_layout(xaxis_title="財報季", yaxis_title="EPS 元")
            col2.plotly_chart(fig, width="stretch")

        # 法說會 guidance（公司財測，從新聞擷取）
        st.divider()
        st.markdown("#### 🎤 法說會 guidance（公司財測）",
                    help="公司在法說會給的財測（全年營收成長/毛利率/資本支出），是分析師預估 EPS 的最上游原料。此處從新聞擷取，best-effort；填 GEMINI_KEY 後可分辨『公司自述 vs 券商解讀』並更精準。")
        gv = _guidance(sid)
        if gv and gv.get("evidence"):
            ga, gb, gc = st.columns(3)
            _metric(ga, "全年營收成長", gv.get("營收成長%"), "%")
            _metric(gb, "毛利率", gv.get("毛利率%"), "%")
            _metric(gc, "資本支出", gv.get("資本支出(億美元)"), " 億美元")
            with st.expander(f"佐證新聞（{len(gv['evidence'])} 則）"):
                for e in gv["evidence"][:8]:
                    st.markdown(f"- `{e['date']}` {e['title']}")
            st.caption("※ 從法說會新聞自動擷取，僅供參考，數字請點原文核對。")
        else:
            st.info("近期未從新聞抓到明確法說會 guidance（可能尚未開法說，或報導未含數字）。")
    else:
        st.warning(f"基本面資料讀取問題：{fund.get('error') if isinstance(fund, dict) else fund}")

# --- 估值 ------------------------------------------------------------------
with tab_val:
    if isinstance(val, dict) and "error" not in val:
        a, b, c, d = st.columns(4)
        _metric(a, "本益比 PER", val.get("per"), help_=HELP["per"])
        _metric(b, "股價淨值比 PBR", val.get("pbr"), help_=HELP["pbr"])
        _metric(c, "本益成長比 PEG", val.get("peg"), help_=HELP["peg"])
        _metric(d, "目前殖利率（FinMind）", val.get("dividend_yield_pct"), "%",
                help_="FinMind 提供的當日殖利率，僅供對照。下方為自行計算的近一年/年化值。")

        # 股利分析（近一年加總 + 年化預估）
        div = val.get("dividend") or {}
        if isinstance(div, dict) and "error" not in div and "note" not in div:
            st.divider()
            st.markdown("#### 💵 現金股利分析")
            e, f, g, h = st.columns(4)
            _metric(e, "近一年現金股利加總", div.get("ttm_cash_dividend"), " 元",
                    help_=f"近一年共配發 {div.get('ttm_payout_count')} 次")
            _metric(f, "近一年殖利率", div.get("yield_ttm_pct"), "%", help_=HELP["yield_ttm"])
            _metric(g, "年化股利預估", div.get("annualized_estimate"), " 元",
                    help_=f"最近一次現金股利 {div.get('recent_cash_dividend')} 元 ×{div.get('ttm_payout_count')} 次。除息日 {div.get('recent_ex_date')}")
            _metric(h, "年化殖利率（預估）", div.get("yield_forward_pct"), "%", help_=HELP["yield_fwd"])
        elif isinstance(div, dict) and "note" in div:
            st.info(f"股利：{div['note']}")

        # 本益比河流圖
        st.divider()
        st.markdown("#### 🌊 本益比河流圖", help=HELP["river"])
        band = _pe_band(sid)
        bdf = band.get("df")
        if isinstance(bdf, pd.DataFrame) and not bdf.empty:
            mults = band["multiples"]
            # 由低到高：綠(便宜) -> 紅(貴)
            shades = ["rgba(38,166,91,0.18)", "rgba(135,196,64,0.18)", "rgba(247,202,24,0.18)",
                      "rgba(230,126,34,0.18)", "rgba(231,76,60,0.18)"]
            fig = go.Figure()
            for i, m in enumerate(mults):
                fig.add_trace(go.Scatter(
                    x=bdf["date"], y=bdf[f"PER {m}"], name=f"{m} 倍", mode="lines",
                    line=dict(width=0.6),
                    fill="tonexty" if i > 0 else None,
                    fillcolor=shades[min(i, len(shades) - 1)],
                    hovertemplate=f"{m}倍: " + "%{y:.0f}<extra></extra>",
                ))
            fig.add_trace(go.Scatter(
                x=bdf["date"], y=bdf["close"], name="收盤價", mode="lines",
                line=dict(color="black", width=2),
                hovertemplate="收盤: %{y:.0f}<extra></extra>",
            ))
            fig.update_layout(title=f"本益比河流圖（目前 PER {band.get('current_per')} 倍）",
                              xaxis_title="日期", yaxis_title="股價", hovermode="x unified")
            st.plotly_chart(fig, width="stretch")
            st.caption(f"PER 帶倍數（取近三年歷史百分位）：{mults}　｜　目前 PER {band.get('current_per')} 倍")
        else:
            st.info("此檔資料不足以繪製本益比河流圖（可能 EPS 為負或歷史太短）。")

        # 📈 EPS 推估器 / 股價推估（本益比評價法）
        st.divider()
        st.markdown("#### 📈 EPS 推估器（拉桿試算股價）",
                    help="以近四季實際財務為基準，調整『預估營收成長』與『預估毛利率』推估 forward EPS，再乘上歷史本益比區間得到合理股價。毛利率低的公司(如鴻海)槓桿很大。")
        f = _eps_fund(sid)
        if f and f.get("shares"):
            cur_gm = round(f["gross_margin"] * 100, 2)
            sens = eps_model.eps_sensitivity_to_margin(f)
            st.caption(f"基準（近四季）：營收 {f['rev']/1e8:,.0f} 億、毛利率 {cur_gm}%、稅率 {f['tax_rate']*100:.1f}%、歸母佔比 {f['parent_ratio']*100:.1f}%、股數 {f['shares']/1e8:.1f} 億　｜　**槓桿：毛利率每 +1pp ≈ EPS {sens:+.2f} 元**")

            gv = _guidance(sid)
            g_growth = gv.get("營收成長%") if gv else None
            g_gm = gv.get("毛利率%") if gv else None
            c1, c2 = st.columns(2)
            rev_g = c1.slider("預估營收成長 (%)", -20.0, 80.0,
                              float(g_growth) if g_growth else 0.0, 1.0)
            gm = c2.slider("預估毛利率 (%)", max(1.0, cur_gm - 4), cur_gm + 8,
                           float(g_gm) if g_gm else cur_gm, 0.1)

            # 毛利率新聞參考（給拉桿一個依據）
            gmn = _gm_news(sid)
            with st.expander("📰 新聞提到的毛利率（設定拉桿前可參考）"):
                got_num = [r for r in gmn if r["毛利率%"] != "—"]
                if got_num:
                    for r in got_num[:6]:
                        st.markdown(f"- `{r['date']}` **{r['毛利率%']}%** ｜ {r['title'][:54]}")
                    st.caption("⚠️ 數字可能是同篇提到的其他個股，請看標題確認。")
                else:
                    st.info(f"新聞標題沒抓到 {(_name(sid) or sid)} 的明確毛利率數字——這類預估多在法說/券商報告內文，免費標題撈不到（需 Gemini 讀內文或看凱基研報）。")
                if gmn:
                    st.caption("毛利率相關新聞：" + "；".join(r["title"][:22] for r in gmn[:4]))

            # PER 倍數設定（答 Q1：可調年數，或自訂）
            st.markdown("**本益比(PER)倍數設定**")
            p1, p2 = st.columns([1, 2])
            yrs = p1.selectbox("歷史取樣年數", [1, 2, 3, 5], index=2,
                               help="PER 低/中/高 = 該期間每日 PER 的 20/50/80 百分位。再評等中的股票(如鴻海)可選短年數或改自訂。")
            band = _pe_band3(sid, yrs)
            hist_mults = band.get("multiples") or []
            manual = p2.checkbox("自訂 PER（覆蓋歷史）", help="若你認為產業/題材讓它該享有不同評價，可手動輸入")
            if manual or len(hist_mults) < 3:
                base_lo = hist_mults[0] if len(hist_mults) >= 3 else 10.0
                base_mid = hist_mults[1] if len(hist_mults) >= 3 else 15.0
                base_hi = hist_mults[2] if len(hist_mults) >= 3 else 20.0
                q1, q2, q3 = st.columns(3)
                lo = q1.number_input("低 PER", 1.0, 100.0, float(round(base_lo, 1)), 0.5)
                mid = q2.number_input("中 PER", 1.0, 100.0, float(round(base_mid, 1)), 0.5)
                hi = q3.number_input("高 PER", 1.0, 100.0, float(round(base_hi, 1)), 0.5)
                mults = [lo, mid, hi]
                src = "自訂"
            else:
                mults = hist_mults
                src = f"近{yrs}年歷史百分位(20/50/80)"

            eps_fwd = eps_model.project_eps(f, rev_g, gm)
            cur_price = price.get("close") if isinstance(price, dict) else None
            labels = ["便宜(PER低)", "合理(PER中)", "昂貴(PER高)"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("推估 EPS", f"{eps_fwd:.2f}", f"{eps_fwd - f['eps_ttm']:+.2f} vs TTM")
            for lab, mlt, col in zip(labels, mults, (m2, m3, m4)):
                tp = eps_fwd * mlt
                up = (tp / cur_price - 1) * 100 if cur_price else None
                col.metric(f"{lab} ×{mlt}", f"{tp:,.0f}",
                           f"{up:+.1f}%" if up is not None else None, delta_color="inverse")
            st.caption(f"推估 EPS {eps_fwd:.2f} × PER {mults}（{src}）　｜　現價 {cur_price}　｜　目前 PER {band.get('current_per')}（漲跌幅%為台股紅漲綠跌）")
        else:
            st.info("此檔資料不足以推估 EPS（可能缺財報、股本或 EPS 為負）。")

        # 分析師目標價（從新聞擷取，best-effort）
        st.divider()
        st.markdown("#### 🎯 分析師目標價", help=HELP["target"])
        tp_news = _tp_news(sid)  # 專門搜目標價的新聞 + 一般新聞
        _ref = price.get("close") if isinstance(price, dict) else None
        tps = _extract_target_prices(tp_news, _ref) if tp_news is not None and not tp_news.empty else []
        if tps:
            tdf = pd.DataFrame(tps)
            st.dataframe(
                tdf[["date", "來源/券商", "目標價", "title"]],
                width="stretch", hide_index=True,
                column_config={"title": "新聞標題"},
            )
            st.caption("※ 只列出新聞標題中**有具名券商/機構**者（瑞銀、大摩、高盛、里昂…），泛稱『外資/法人』與媒體名一律不列。仍建議點原文核對。")
        else:
            st.info("近期新聞中未擷取到明確目標價數字。註：免費資料源沒有結構化的各券商目標價（屬付費資料），"
                    "此功能靠新聞擷取，量取決於新聞多寡——填 FinMind token 後新聞變多會更有料。")
    else:
        st.warning(f"估值資料讀取問題：{val.get('error') if isinstance(val, dict) else val}")

# --- 相關新聞 --------------------------------------------------------------
with tab_news:
    news = _news(sid)
    if news is not None and not news.empty:
        st.caption(f"共 {len(news)} 則（來源：Google News + FinMind 整合去重）")
        _ai_summary_block(news.head(50), "news")
        st.divider()
        for _, r in news.head(40).iterrows():
            d = str(r["date"])[:16]
            st.markdown(f"- `{d}` **[{r['source']}]** [{r['title']}]({r['link']})")
    else:
        st.info("近期查無相關新聞。")

# --- 投顧動向 --------------------------------------------------------------
with tab_report:
    st.caption(
        "ℹ️ MoneyDJ 免費研究報告區已停更（僅存 2011 年前存檔），故改以「近期新聞中與投顧/"
        "法人/目標價/評等相關者」呈現分析師動向。"
    )
    news = _news(sid)
    if news is not None and not news.empty:
        mask = news["title"].str.contains("|".join(ANALYST_KEYWORDS), na=False)
        hits = news[mask]
        if not hits.empty:
            st.caption(f"過濾出 {len(hits)} 則投顧/法人相關")
            _ai_summary_block(hits.head(30), "report")
            st.divider()
            for _, r in hits.head(30).iterrows():
                d = str(r["date"])[:16]
                st.markdown(f"- `{d}` **[{r['source']}]** [{r['title']}]({r['link']})")
        else:
            st.info("近期新聞中沒有明顯的投顧/法人/目標價相關內容。")
    else:
        st.info("近期查無新聞。")

# --- 產業 / 供應鏈 ---------------------------------------------------------
with tab_industry:
    info = fm.stock_info(sid)
    cats = sorted(set(info["industry_category"].dropna())) if not info.empty else []
    st.markdown(f"**產業分類：** {('、'.join(cats)) if cats else '—'}")
    view = None
    for c in cats:
        view = industry_mod.get_industry_view(c) or view
    if view:
        st.info(view["desc"])
        u, m, d = st.columns(3)
        with u:
            st.markdown("##### ⬆️ 上游")
            for seg, stocks in view["upstream"]:
                st.markdown(f"**{seg}**\n\n{stocks}")
        with m:
            st.markdown("##### ↔️ 中游")
            for seg, stocks in view["midstream"]:
                st.markdown(f"**{seg}**\n\n{stocks}")
        with d:
            st.markdown("##### ⬇️ 下游")
            for seg, stocks in view["downstream"]:
                st.markdown(f"**{seg}**\n\n{stocks}")
        st.caption("※ 上下游與代表個股為靜態整理，僅供建立產業輪廓參考。")
    else:
        st.warning(f"尚未內建「{('、'.join(cats)) or '此'}」產業的供應鏈整理。")

    # AI 生成本公司產業地位與上下游
    st.divider()
    if gem.is_configured():
        if st.button("🤖 用 AI 生成本公司的產業地位與上下游"):
            with st.spinner("Gemini 生成中…"):
                try:
                    prompt = (
                        f"請用繁體中文，針對台股 {_name(sid) or ''}({sid})，"
                        f"簡述：①它在所屬產業（{'、'.join(cats)}）的定位與市佔/競爭力 "
                        f"②上游供應商類型與代表台股 ③下游客戶/應用與代表台股 ④主要競爭對手。"
                        f"條列、精簡、避免投資建議。"
                    )
                    st.success(gem.generate(prompt))
                except Exception as e:  # noqa: BLE001
                    st.error(f"生成失敗：{type(e).__name__}: {e}")
    else:
        st.caption("🤖 想要『本公司』量身的產業地位與上下游分析？填 `.env` 的 `GEMINI_KEY` 並重啟後即可一鍵生成。")

st.sidebar.divider()
st.sidebar.caption("⚠️ 僅供個人研究，非投資建議。")
