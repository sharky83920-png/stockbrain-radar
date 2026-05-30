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

from src.analysis import industry as industry_mod
from src.analysis import news_digest
from src.analysis.valuation import pe_band
from src.data import finmind_client as fm
from src.data import gemini_client as gem
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


# 從新聞標題擷取「目標價/上看/看到/調升至 ___ 元」（best-effort，免費資料無結構化券商目標價）
_TP_PATTERNS = [
    r"目標價[^0-9]{0,10}([0-9][0-9,]{1,5}(?:\.[0-9])?)",
    r"上看[^0-9]{0,6}([0-9][0-9,]{1,5})",
    r"看[到上][^0-9]{0,6}([0-9][0-9,]{1,5})\s*元",
    r"(?:調升|上修|喊上|上調|調漲)[^0-9]{0,8}([0-9][0-9,]{1,5})\s*元",
]
_BROKERS = ["大摩", "小摩", "摩根士丹利", "摩根大通", "摩根", "高盛", "瑞銀", "UBS", "美林", "花旗",
            "野村", "瑞信", "麥格理", "里昂", "傑富瑞", "Jefferies", "匯豐", "星展", "巴克萊",
            "德意志", "Factset", "凱基", "元大", "富邦", "群益", "中信", "第一金", "兆豐", "外資",
            "投信", "法人", "分析師", "杜金龍"]


def _extract_target_prices(news_df, ref_price=None):
    lo = hi = None
    if ref_price:
        lo, hi = ref_price * 0.4, ref_price * 2.6  # 合理區間，濾掉同篇其他個股的目標價
    rows = []
    seen = set()
    for _, r in news_df.iterrows():
        title = str(r["title"])
        if "目標價" not in title and "上看" not in title and not re.search(r"看[到上].{0,6}元", title):
            continue
        prices = []
        for pat in _TP_PATTERNS:
            prices += [p.replace(",", "") for p in re.findall(pat, title)]
        vals = []
        for p in prices:
            try:
                v = float(p)
            except ValueError:
                continue
            if v < 10:
                continue
            if lo and not (lo <= v <= hi):
                continue
            vals.append(p)
        prices = vals
        if not prices:
            continue
        broker = next((b for b in _BROKERS if b in title), None) or str(r.get("source", "—"))
        price_str = "、".join(sorted(set(prices), key=lambda x: float(x)))
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

tab_chip, tab_fund, tab_val, tab_news, tab_report, tab_industry = st.tabs(
    ["🎯 籌碼面", "📊 基本面", "💰 估值", "📰 相關新聞", "📑 投顧動向", "🏭 產業/供應鏈"]
)


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
            st.caption("※ 自動從新聞標題擷取，已用現價 0.4~2.6 倍過濾；仍可能含同篇提及的其他個股，請點原文核對。")
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
