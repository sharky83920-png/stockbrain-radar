"""00878 蒸餾儀表板 —— 追蹤成分股、加減碼/換股、配息拆解、推估持股成本。

Streamlit 多頁：放在 pages/ 下，啟動 dashboard.py 後會自動出現在側邊欄。
資料地基見 src/data/etf_holdings.py（857 天持股史）、etf_dividends.py；
分析見 src/analysis/etf_dividend_source.py（配息拆解）、etf_cost_basis.py（推估成本）。
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data import etf_holdings as eh
from src.data import etf_dividends as ed
from src.data import etf_meta
from src.analysis import etf_dividend_source as ds
from src.analysis import etf_cost_basis as cb

FUND = "00878"
# 台股慣例配色：紅＝漲/賺/便宜、綠＝跌/賠/貴
UP_RED, DOWN_GREEN, GRAY = "#d62728", "#1ca35a", "#808495"

st.set_page_config(page_title="00878 蒸餾", page_icon="🧪", layout="wide")


# --- 快取資料載入 -------------------------------------------------------
@st.cache_data(ttl=3600)
def _cost_basis():
    return cb.estimate_cost_basis(FUND)


@st.cache_data(ttl=3600)
def _dividends():
    return ed.fetch_dividends(FUND)


@st.cache_data(ttl=3600)
def _annual_source():
    return ds.annual_source(FUND, 2023)


@st.cache_data(ttl=3600)
def _events():
    return eh.constituent_events(FUND)


@st.cache_data(ttl=1800)
def _assets():
    return eh.fetch_assets(FUND)


def _pos_red_neg_green(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return f"color:{UP_RED};font-weight:600"
    if x < 0:
        return f"color:{DOWN_GREEN};font-weight:600"
    return ""


# --- 標頭 ---------------------------------------------------------------
st.title("🧪 00878 蒸餾儀表板")
st.caption("國泰永續高股息 ETF ｜ 追蹤成分股、加減碼、配息來源、推估持股成本 ── 為了自己挑股")

date, latest = eh.latest(FUND)
if latest.empty:
    st.error("尚無持股資料。請先執行 `python scripts/etf_backfill.py 2023-01-01` 回補持股歷史。")
    st.stop()

assets = _assets()
c1, c2, c3, c4 = st.columns(4)
c1.metric("持股資料日", date)
c2.metric("基金規模", f"{(assets.get('fund_nav_total') or 0)/1e8:,.0f} 億" if assets else "—")
c3.metric("每單位淨值", f"{assets.get('nav_per_unit')}" if assets else "—")
c4.metric("成分股數", f"{len(latest)} 檔")

tab_hold, tab_chg, tab_div, tab_rule = st.tabs(
    ["📦 持股 & 推估成本", "🔄 加減碼 / 換股", "💰 配息拆解", "📖 指數規則"])

# ========== 持股 & 推估成本 ==========
with tab_hold:
    with st.spinner("計算推估成本中（首次載入抓 FinMind 股價，約數秒）…"):
        cost = _cost_basis()
    if cost.empty:
        st.warning("推估成本計算不到資料。")
    else:
        tot_shares_val = (cost["shares"] * cost["current_price"]).sum()
        tot_cost_val = (cost["shares"] * cost["est_avg_cost"]).sum()
        pnl_pct = (tot_shares_val / tot_cost_val - 1) * 100 if tot_cost_val else 0
        m1, m2 = st.columns(2)
        m1.metric("整體推估未實現損益", f"{pnl_pct:+.1f}%",
                  help="以推估平均成本對照現價，加權合計。僅估算。")
        m2.metric("推估成本最低（相對現價最賺）",
                  f"{cost.loc[cost.unreal_pnl_pct.idxmax(),'name']} "
                  f"{cost.unreal_pnl_pct.max():+.0f}%")

        show = cost.rename(columns={
            "code": "代碼", "name": "名稱", "weight": "權重%", "shares": "持股數",
            "est_avg_cost": "推估成本", "current_price": "現價",
            "unreal_pnl_pct": "推估未實現%", "first_held": "首次持有"})
        show = show[["代碼", "名稱", "權重%", "持股數", "推估成本", "現價",
                     "推估未實現%", "首次持有"]]
        styled = (show.style
                  .map(_pos_red_neg_green, subset=["推估未實現%"])
                  .format({"權重%": "{:.2f}", "持股數": "{:,.0f}",
                           "推估成本": "{:.2f}", "現價": "{:.2f}",
                           "推估未實現%": "{:+.1f}"}))
        st.dataframe(styled, use_container_width=True, height=560, hide_index=True)
        st.caption("⚠️ 推估成本＝以持股史逐日股數變化 × 當日收盤價，移動加權平均。"
                   "非基金真實帳務，加碼日成交價以收盤近似，方向參考用。紅賺綠賠。")

# ========== 加減碼 / 換股 ==========
with tab_chg:
    st.subheader("換股事件（成分股新增／剔除）")
    st.caption("這是真正的換股訊號。指數每年 5、11 月半年審為主（見『指數規則』）。"
               "每日創造/贖回造成的等比微幅漲跌不算在這。")
    ev = _events()
    if ev.empty:
        st.info("持股史中沒有成分股進出事件。")
    else:
        ev_show = ev.copy()
        ev_show["新增"] = ev_show["added"].apply(lambda x: "　".join(f"➕{n}" for n in x))
        ev_show["剔除"] = ev_show["removed"].apply(lambda x: "　".join(f"➖{n}" for n in x))
        ev_show = ev_show[["date", "剔除", "新增"]].rename(columns={"date": "日期"})
        st.dataframe(ev_show.iloc[::-1], use_container_width=True, hide_index=True, height=430)

    st.divider()
    st.subheader("最近一次股數變化")
    dates = eh.stored_dates(FUND)
    if len(dates) >= 2:
        chg = eh.share_changes(FUND, dates[-1], dates[-2])
        moved = chg[chg["event"].isin(["加碼", "減碼", "新增", "剔除"])].head(20)
        if moved.empty:
            st.write(f"（{dates[-2]} → {dates[-1]} 股數無變化）")
        else:
            mv = moved.rename(columns={
                "stock_code": "代碼", "stock_name": "名稱", "event": "動作",
                "prev_shares": "前股數", "shares": "現股數", "pct": "變化%"})
            st.caption(f"{dates[-2]} → {dates[-1]}")
            st.dataframe(
                mv[["代碼", "名稱", "動作", "前股數", "現股數", "變化%"]].style.format(
                    {"前股數": "{:,.0f}", "現股數": "{:,.0f}", "變化%": "{:+.1f}"}),
                use_container_width=True, hide_index=True, height=380)

# ========== 配息拆解 ==========
with tab_div:
    st.subheader("配息來源：股利 vs 資本利得")
    ann = _annual_source()
    div = _dividends()

    if not ann.empty:
        full = ann[ann["year"] < 2026]
        rec = full["received_div_per_unit"].sum()
        paid = full["paid_per_unit"].sum()
        cover = rec / paid * 100 if paid else 0
        k1, k2, k3 = st.columns(3)
        k1.metric("動用收益平準金期數", f"{(div['principal_pct']>0).sum()} / {len(div)}",
                  help="官方兩分法。00878 至今從未動用平準金＝沒有配到你的本金。")
        k2.metric("股利覆蓋率（2023–25）", f"{cover:.0f}%",
                  help="成分股實收現金股利 ÷ 實際配息。")
        k3.metric("推估來自資本利得", f"≈{100-cover:.0f}%",
                  help="平準金＝0，故配息扣掉股利後的缺口來自已實現資本利得。")

        st.markdown(f"> **關鍵**：00878 從沒動用平準金（不是掏你本金），"
                    f"但配息裡**只有約 {cover:.0f}% 是成分股真正發的現金股利，"
                    f"另外約 {100-cover:.0f}% 是基金賣股實現的資本利得**。"
                    f"高殖利率有一半是把你帳上的增值『實現』發還給你。")

        plot = ann.copy()
        plot["資本利得(估)"] = (plot["paid_per_unit"] - plot["received_div_per_unit"]).clip(lower=0)
        fig = go.Figure()
        fig.add_bar(x=plot["year"], y=plot["received_div_per_unit"],
                    name="現金股利", marker_color="#185FA5")
        fig.add_bar(x=plot["year"], y=plot["資本利得(估)"],
                    name="資本利得(估)", marker_color="#E8862A")
        fig.update_layout(barmode="stack", height=340, yaxis_title="每單位配息(元)",
                          legend=dict(orientation="h", y=1.1), margin=dict(t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("2026 為未滿整年（4 季只發生 2 季），僅供參考不列入覆蓋率。"
                   "拆解為估算：除息日持股用最近快照近似。")

    st.divider()
    st.subheader("歷史配息與兩分法組成")
    if not div.empty:
        dv = div.rename(columns={
            "allot_ym": "配息年月", "pay_money": "每單位", "year_yield": "年化率%",
            "income_pct": "淨收益%", "principal_pct": "平準金%",
            "ex_date": "除息日", "pay_date": "發放日"})
        st.dataframe(
            dv[["配息年月", "每單位", "年化率%", "淨收益%", "平準金%", "除息日", "發放日"]]
            .style.format({"每單位": "{:.3f}", "年化率%": "{:.2f}",
                           "淨收益%": "{:.0f}", "平準金%": "{:.0f}"}),
            use_container_width=True, hide_index=True, height=360)

# ========== 指數規則 ==========
with tab_rule:
    st.subheader("MSCI 臺灣 ESG 永續高股息精選 30 指數 —— 蒸餾用的『配方』")
    sel = etf_meta.SELECTION
    st.markdown(f"""
**選股（你要複製的尺）**
- 母體：{sel['universe']}
- 篩選：ESG 評級 ≥ **{sel['filters']['esg_rating_min']}**、爭議分數 ≥ **{sel['filters']['esg_controversy_min']}**、
  市值 ≥ **7 億美元**、年度 EPS > 0、殖利率穩健
- 排序：**股利分數 = {sel['dividend_score_weights']['ttm_yield']}×近12月殖利率
  + {sel['dividend_score_weights']['avg3y_yield']}×近三年平均殖利率**，取前 {sel['target_constituents']} 檔、股利分數加權

**換股時程**：每年 **5、11 月**半年審（主要）＋ 2、8 月季審。生效前 5 個交易日過渡、月底完成。
> 判讀加減碼：一檔被**剔除**＝連緩衝區（第 {etf_meta.SELECTION['buffer_rank_range'][1]} 名）都掉出＝真訊號；
> **減碼**常只是撞到單檔 **{etf_meta.WEIGHT_CAPS['single_stock_max']*100:.0f}%** 權重上限，非看壞。

**費用**：內扣約 **{etf_meta.FEES['effective_expense_estimate']*100:.2f}%/年**（經理 0.25% + 保管 0.03%）。
""")
    st.caption("完整版：個股研究/00878蒸餾/00878_指數規則與配息機制.md　｜　常數：src/data/etf_meta.py")
