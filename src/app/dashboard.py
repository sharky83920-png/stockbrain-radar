"""StockBrain Radar — 個股研究 Dashboard (Streamlit)。

啟動：streamlit run src/app/dashboard.py
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data import finmind_client as fm
from src.data.snapshot import build_snapshot

st.set_page_config(page_title="StockBrain Radar", page_icon="📡", layout="wide")


@st.cache_data(ttl=3600)
def _snapshot(sid: str):
    return build_snapshot(sid)


@st.cache_data(ttl=3600)
def _price(sid: str):
    return fm.stock_price(sid, days=120).sort_values("date")


@st.cache_data(ttl=3600)
def _inst(sid: str):
    return fm.institutional_investors(sid, days=45).sort_values("date")


def _metric(col, label, value, suffix="", help_=None):
    txt = "—" if value is None else f"{value}{suffix}"
    col.metric(label, txt, help=help_)


# --- Sidebar ---------------------------------------------------------------
st.sidebar.title("📡 StockBrain Radar")
sid = st.sidebar.text_input("股票代號", value="2330").strip()
st.sidebar.caption("資料來源：FinMind。當日快取，研究用途。")

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
    _metric(c1, "收盤", price.get("close"))
    delta = price.get("change_pct")
    c2.metric("漲跌幅", f"{price.get('change')}", f"{delta}%" if delta is not None else None)
    _metric(c3, "PER", val.get("per") if isinstance(val, dict) else None)
    _metric(c4, "PEG", val.get("peg") if isinstance(val, dict) else None,
            help_="PER / EPS年增率。<1 偏便宜，>2 偏貴")
    _metric(c5, "ROE(TTM)", fund.get("roe_ttm_pct") if isinstance(fund, dict) else None, "%")
    st.caption(f"資料日：{price.get('date')}　成交量：{price.get('volume_lots'):,} 張")
else:
    st.error(f"查無 {sid} 的價格資料，請確認代號。")

tab_chip, tab_fund, tab_val = st.tabs(["🎯 籌碼面", "📊 基本面", "💰 估值"])

# --- 籌碼面 ----------------------------------------------------------------
with tab_chip:
    if isinstance(chips, dict) and "error" not in chips:
        a, b, c, d = st.columns(4)
        _metric(a, f"外資淨買賣 (近{chips.get('window_days','?')}日)", chips.get("foreign_net_20d_lots"), " 張")
        _metric(b, "投信淨買賣", chips.get("trust_net_20d_lots"), " 張")
        _metric(c, "外資持股", chips.get("foreign_holding_pct"), "%")
        _metric(d, "融資餘額", f"{chips.get('margin_balance_lots'):,}" if chips.get("margin_balance_lots") is not None else None, " 張",
                help_=f"近45日變化 {chips.get('margin_change_lots')} 張")
        st.divider()
        inst = _inst(sid)
        if not inst.empty:
            inst = inst.copy()
            inst["淨買賣(張)"] = (inst["buy"] - inst["sell"]) / 1000.0
            name_map = {"Foreign_Investor": "外資", "Investment_Trust": "投信",
                        "Dealer_self": "自營(自行)", "Dealer_Hedging": "自營(避險)"}
            inst["法人"] = inst["name"].map(name_map).fillna(inst["name"])
            keep = inst[inst["法人"].isin(["外資", "投信"])]
            fig = px.bar(keep, x="date", y="淨買賣(張)", color="法人", barmode="group",
                         title="三大法人每日淨買賣（近交易日）")
            st.plotly_chart(fig, width="stretch")
    else:
        st.warning(f"籌碼資料讀取問題：{chips.get('error') if isinstance(chips, dict) else chips}")

# --- 基本面 ----------------------------------------------------------------
with tab_fund:
    if isinstance(fund, dict) and "error" not in fund:
        a, b, c, d = st.columns(4)
        _metric(a, "毛利率", fund.get("gross_margin_pct"), "%")
        _metric(b, "營業利益率", fund.get("operating_margin_pct"), "%")
        _metric(c, "負債比", fund.get("debt_ratio_pct"), "%")
        _metric(d, "EPS(TTM)", fund.get("eps_ttm"))
        st.caption(f"最新財報季：{fund.get('latest_quarter')}　EPS年增率：{fund.get('eps_yoy_pct')}%")
        st.divider()
        col1, col2 = st.columns(2)
        rev = fund.get("revenue_yoy_recent") or []
        if rev:
            rdf = pd.DataFrame(rev)
            fig = px.bar(rdf, x="month", y="yoy_pct", title="月營收年增率 (%)", text="yoy_pct")
            col1.plotly_chart(fig, width="stretch")
        eps = fund.get("eps_recent") or []
        if eps:
            edf = pd.DataFrame(eps)
            fig = px.bar(edf, x="q", y="eps", title="近四季 EPS", text="eps")
            col2.plotly_chart(fig, width="stretch")
    else:
        st.warning(f"基本面資料讀取問題：{fund.get('error') if isinstance(fund, dict) else fund}")

# --- 估值 ------------------------------------------------------------------
with tab_val:
    if isinstance(val, dict) and "error" not in val:
        a, b, c, d = st.columns(4)
        _metric(a, "本益比 PER", val.get("per"))
        _metric(b, "股價淨值比 PBR", val.get("pbr"))
        _metric(c, "殖利率", val.get("dividend_yield_pct"), "%")
        _metric(d, "PEG", val.get("peg"))
        st.divider()
        p = _price(sid)
        if not p.empty:
            fig = px.line(p, x="date", y="close", title="近 120 日收盤價")
            st.plotly_chart(fig, width="stretch")
    else:
        st.warning(f"估值資料讀取問題：{val.get('error') if isinstance(val, dict) else val}")

st.sidebar.divider()
st.sidebar.caption("⚠️ 僅供個人研究，非投資建議。")
