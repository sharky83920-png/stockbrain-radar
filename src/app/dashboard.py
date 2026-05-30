"""StockBrain Radar — 個股研究 Dashboard (Streamlit)。

啟動：streamlit run src/app/dashboard.py
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.analysis.valuation import pe_band
from src.data import finmind_client as fm
from src.data import gemini_client as gem
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
    "debt": "負債比 = 總負債 ÷ 總資產。<60% 較安全。",
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


@st.cache_data(ttl=3600)
def _news(sid: str):
    return fm.news(sid, days=21).sort_values("date", ascending=False)


def _metric(col, label, value, suffix="", help_=None):
    txt = "—" if value is None else f"{value}{suffix}"
    col.metric(label, txt, help=help_)


# --- Sidebar ---------------------------------------------------------------
st.sidebar.title("📡 StockBrain Radar")
sid = st.sidebar.text_input("股票代號（如 2330）", value="2330").strip()
st.sidebar.caption("資料來源：FinMind。當日快取，僅供個人研究。")

if not sid:
    st.info("← 在左側輸入股票代號")
    st.stop()

snap = _snapshot(sid)
price = snap.get("price", {})
chips = snap.get("chips", {})
fund = snap.get("fundamentals", {})
val = snap.get("valuation", {})

# --- Header ----------------------------------------------------------------
st.title(f"{sid} 個股研究")
if isinstance(price, dict) and "close" in price:
    c1, c2, c3, c4, c5 = st.columns(5)
    _metric(c1, "收盤價", price.get("close"))
    delta = price.get("change_pct")
    c2.metric("漲跌幅", f"{price.get('change')}", f"{delta}%" if delta is not None else None)
    _metric(c3, "本益比 PER", val.get("per") if isinstance(val, dict) else None, help_=HELP["per"])
    _metric(c4, "本益成長比 PEG", val.get("peg") if isinstance(val, dict) else None, help_=HELP["peg"])
    _metric(c5, "ROE 股東權益報酬率(近四季)", fund.get("roe_ttm_pct") if isinstance(fund, dict) else None, "%", help_=HELP["roe"])
    st.caption(f"資料日：{price.get('date')}　成交量：{price.get('volume_lots'):,} 張")
else:
    st.error(f"查無 {sid} 的價格資料，請確認代號。")

tab_chip, tab_fund, tab_val, tab_news, tab_report = st.tabs(
    ["🎯 籌碼面", "📊 基本面", "💰 估值", "📰 相關新聞", "📑 投顧動向"]
)


def _ai_summary_block(titles, key_suffix):
    """共用：一顆 AI 摘要按鈕 + 結果。"""
    if not gem.is_configured():
        st.caption("🤖 AI 摘要：請在專案 `.env` 設定 `GEMINI_KEY`（與你 GAS 晨報同一把）後即可使用。")
        return
    if st.button("🤖 用 AI 摘要這些內容", key=f"ai_{key_suffix}"):
        with st.spinner("Gemini 摘要中…"):
            try:
                st.success(gem.summarize_news(titles, sid))
            except Exception as e:  # noqa: BLE001
                st.error(f"摘要失敗：{type(e).__name__}: {e}")

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
        a, b, c, d = st.columns(4)
        _metric(a, "毛利率", fund.get("gross_margin_pct"), "%", help_=HELP["gross"])
        _metric(b, "營業利益率", fund.get("operating_margin_pct"), "%", help_=HELP["op"])
        _metric(c, "負債比", fund.get("debt_ratio_pct"), "%", help_=HELP["debt"])
        _metric(d, "每股盈餘 EPS（近四季）", fund.get("eps_ttm"), help_=HELP["eps_ttm"])
        st.caption(f"最新財報季：{fund.get('latest_quarter')}　EPS 年增率（與去年同季比）：{fund.get('eps_yoy_pct')}%")
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
    else:
        st.warning(f"估值資料讀取問題：{val.get('error') if isinstance(val, dict) else val}")

# --- 相關新聞 --------------------------------------------------------------
with tab_news:
    news = _news(sid)
    if news is not None and not news.empty:
        st.caption(f"近 21 天共 {len(news)} 則（來源：FinMind 聚合）")
        _ai_summary_block(list(news.head(40)["title"]), "news")
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
            _ai_summary_block(list(hits.head(30)["title"]), "report")
            st.divider()
            for _, r in hits.head(30).iterrows():
                d = str(r["date"])[:16]
                st.markdown(f"- `{d}` **[{r['source']}]** [{r['title']}]({r['link']})")
        else:
            st.info("近期新聞中沒有明顯的投顧/法人/目標價相關內容。")
    else:
        st.info("近期查無新聞。")

st.sidebar.divider()
st.sidebar.caption("⚠️ 僅供個人研究，非投資建議。")
