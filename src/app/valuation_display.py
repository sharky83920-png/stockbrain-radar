"""估值分析展示元件
帶小問號說明每個計算怎麼算出來的
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date
from typing import Dict, Optional

from src.analysis import multidim_valuation as mdv
from src.analysis import fundamental_forecast as ff
from src.analysis import sun_dcf


# 名詞解釋（供 st.metric 的 help= 用，hover 即顯示小問號 ❓）
VALUATION_HELP = {
    "peg": "本益成長比 PEG（Price/Earnings to Growth）= 預估本益比 ÷ 每股盈餘EPS年增率(%)。"
           "<0.8 極度低估、0.8-1.0 低估、1.0-1.5 合理、>1.5 昂貴。"
           "本系統年增率用『真實資料』：預估EPS(孫慶龍) vs 最近完整年度實際EPS。",
    "pcf": "股價現金流比 P/CF（Price/Cash Flow，又稱本流法）= 股價 ÷ 每股自由現金流FCF。"
           "自由現金流量 FCF（Free Cash Flow）= 近四季營業現金流 − 資本支出。"
           "檢查獲利是否有現金支撐；FCF 為負代表暫無現金支撐，本流法不適用。",
    "advisor_pe": "從投顧報告反推：目標價 ÷ 預估每股盈餘EPS = 隱含本益比P/E。優先用報告自己的預估EPS，"
                  "沒有就用我們孫慶龍的預估EPS（會標示）。多家取平均。",
    "eps_forecast": "預估每股盈餘 EPS（Earnings Per Share）來自孫慶龍8步驟法：①今年累積營收年增率YoY "
                    "②去年全年營收 ③預估營收＝②×(1＋①) ④近四季母公司淨利率 ⑤預估淨利＝③×④ "
                    "⑥預估EPS＝⑤÷發行股數。這是『預估值』，與投顧預估可能不同。",
}


def _help_icon(key: str) -> str:
    """每個 st.metric 已用 help= 帶出小問號 ❓ tooltip，label 不再內嵌，故回空字串。"""
    return ""


def show_sun_forecast(sid: str):
    """展示孫慶龍8步驟法的估算結果"""
    st.markdown("### 🔢 孫慶龍8步驟法基本面估算")

    result = ff.compute(sid)

    if not result:
        st.error("無法取得基本面數據")
        return

    # 顯示8個步驟
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        ytd_m = result.get("ytd_months")
        yoy = result.get("ytd_yoy_pct")
        st.metric(
            f"①累積營收年增率 YoY" + _help_icon("eps_forecast"),
            f"{yoy:+.1f}%" if yoy else "—",
            help="年增率 YoY（Year over Year）＝今年前N月累積營收 ÷ 去年同期累積營收 − 1。"
        )

    with col2:
        prev_rev = result.get("prev_year_revenue")
        st.metric(
            "②去年全年營收" + _help_icon("eps_forecast"),
            f"{prev_rev/1e8:.0f}億" if prev_rev else "—",
            help="上年度完整全年營收"
        )

    with col3:
        est_rev = result.get("est_revenue")
        st.metric(
            "③預估今年營收" + _help_icon("eps_forecast"),
            f"{est_rev/1e8:.0f}億" if est_rev else "—",
            help="去年全年 × (1 + YoY%)"
        )

    with col4:
        net_margin = result.get("net_margin_ttm_pct")
        st.metric(
            "④近四季淨利率 TTM" + _help_icon("eps_forecast"),
            f"{net_margin}%" if net_margin else "—",
            help="近四季 TTM（Trailing Twelve Months，最近12個月）。"
                 "淨利率＝近四季稅後淨利（每股盈餘EPS×股數）÷ 近四季營收。"
        )

    col5, col6, col7, col8 = st.columns(4)

    with col5:
        est_ni = result.get("est_net_income")
        st.metric(
            "⑤預估稅後淨利" + _help_icon("eps_forecast"),
            f"{est_ni/1e8:.1f}億" if est_ni else "—",
            help="預估營收 × 淨利率"
        )

    with col6:
        est_eps = result.get("est_eps")
        st.metric(
            "⑥預估每股盈餘 EPS" + _help_icon("eps_forecast"),
            f"{est_eps:.2f}元" if est_eps else "—",
            help="每股盈餘 EPS（Earnings Per Share）＝預估稅後淨利 ÷ 發行股數。"
        )

    with col7:
        payout_ratio = result.get("payout_ratio_avg_pct")
        st.metric(
            "⑦平均分配率" + _help_icon("eps_forecast"),
            f"{payout_ratio:.1f}%" if payout_ratio else "—",
            help="近三年（現金股利 ÷ 每股盈餘EPS）平均值"
        )

    with col8:
        est_div = result.get("est_dividend")
        st.metric(
            "⑧預估現金股利" + _help_icon("eps_forecast"),
            f"{est_div:.2f}元" if est_div else "—",
            help="預估每股盈餘EPS × 平均分配率"
        )

    # 顯示摘要
    if result.get("errors"):
        st.warning(f"⚠️ 計算提醒：{'; '.join(result['errors'])}")

    return result


def _upside(target, price):
    if not target or not price:
        return None
    return (target / price - 1) * 100


# ══════════════════════════════════════════════════════════════════════════
# 內在價值法：孫慶龍 DCF（《超前部署賺好股》第 4 篇）
# ══════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600)
def _dcf_inputs_cached(sid: str):
    return sun_dcf.gather_dcf_inputs(sid)


@st.cache_data(ttl=3600)
def _cash_return_cached(sid: str, current_price: float):
    return sun_dcf.cash_return(sid, current_price)


def show_sun_dcf(sid: str, current_price: Optional[float]) -> Optional[Dict]:
    """內在價值法：現金流量折現 DCF（孫慶龍《超前部署賺好股》做法）。
    回傳 dcf_table 結果（含 buy_price/sell_price），供目標價彙整表使用。"""
    st.markdown("## 🏦 內在價值法：現金流量折現 DCF（孫慶龍）")
    st.caption("DCF＝Discounted Cash Flow（現金流量折現法）。出處《超前部署賺好股》第4篇：**企業價值 = 每股淨值 ＋ Σ 未來20年每股盈餘EPS折現**。"
               "盈餘成長率 = 5年平均股東權益報酬率ROE × (1−5年平均盈餘分配率)，前10年全速成長、後10年減半。"
               "**買進價 = 10年回收價（隱含年化7.2%）；長期賣出目標 = 20年回收價**。")

    inputs = _dcf_inputs_cached(sid)
    if not inputs:
        st.info("財報資料不足（需至少 3 個完整年度的 EPS 與年底淨值），無法計算 DCF。")
        return None
    if inputs.get("error"):
        st.info(f"DCF 不適用：{inputs['error']}")
        return None

    # ── 折現率參數（書中：無風險利率＝30年公債；風險貼水依競爭態勢 5%~15%）──
    p1, p2 = st.columns([1, 2])
    rf = p1.slider("無風險利率 %（30年公債）", 2.0, 8.0, 4.5, 0.25, key=f"dcf_rf_{sid}",
                   help="書中採美國30年期公債利率（示範時為5%）。利率下降時記得調低——這就是「隨聯準會利率政策滾動調整」。")
    premium = p2.radio("風險貼水（依營運風險/競爭態勢）",
                       [5.0, 10.0, 15.0], index=1, horizontal=True, key=f"dcf_prem_{sid}",
                       format_func=lambda x: {5.0: "5%＝幾乎沒有競爭對手",
                                              10.0: "10%＝一般競爭",
                                              15.0: "15%＝競爭激烈"}[x],
                       help="孫慶龍經驗法則：沒有競爭對手的公司 +5%；競爭者眾 +10%~15%。"
                            "折現率給太高會嚴重低估價值、給太低會買貴，是估值最主觀也最關鍵的一步。")

    t = sun_dcf.dcf_table(inputs, risk_free_pct=rf, risk_premium_pct=premium)

    # ── 5 大財務數據 ──
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("盈餘成長率", f"{inputs['growth_pct']:.2f}%",
              help=f"盈餘成長率＝股東權益報酬率ROE（Return on Equity＝稅後淨利÷股東權益）×(1−盈餘分配率) "
                   f"= {inputs['roe_avg_pct']}% × (1−{inputs['payout_avg_pct']}%)。"
                   f"採 5 年平均，免預測景氣、避開盈餘高峰陷阱。{inputs['basis']}")
    m2.metric("折現率", f"{t['discount_rate_pct']:.2f}%",
              help=f"折現率＝把未來的錢換算成今天價值的利率。無風險利率 {rf}% ＋ 風險貼水 {premium}%。"
                   f"第 n 年折現價＝該年EPS ÷ (1＋折現率)^n。")
    m3.metric(f"基期每股盈餘 EPS（{inputs['eps0_year']}年）", f"{inputs['eps0']:.2f} 元",
              help="每股盈餘 EPS（Earnings Per Share）＝稅後淨利÷股數。此為最近完整年度的全年 EPS，作為第 0 年基準。")
    m4.metric("每股淨值", f"{inputs['bvps']:.2f} 元",
              help=f"{inputs['bvps_date']} 歸屬母公司權益 ÷ 股數。DCF 現值要加回淨值。")

    # ── 三檔價位 ──
    st.write("")
    v1, v2, v3 = st.columns(3)
    for col, key_, label, irr, hint in (
        (v1, "price_5y", "5年回收價（積極）", 14.9, "只給願意等的深度便宜價：用第5年累計折現價買進，隱含年化報酬 14.9%。"),
        (v2, "buy_price", "★ 買進價（10年回收）", 7.2, "書中設定的買進價：第10年累計折現價，隱含年化報酬 7.2%（台積電例：557元）。"),
        (v3, "sell_price", "賣出目標（20年回收）", 3.55, "長期賣出目標＝20年全部價值（台積電例：1,019元）。漲到這裡代表未來20年的價值已被反映。"),
    ):
        tgt = t.get(key_)
        up = _upside(tgt, current_price)
        col.metric(label, f"{tgt:,.0f} 元" if tgt else "—",
                   f"{up:+.1f}%" if up is not None else None,
                   delta_color="inverse",
                   help=hint + f"　隱含年化 {irr}%＝書中回收年數對照表。")

    # ── 信號（台股慣例：便宜可買=紅、貴=綠）──
    if current_price and t.get("buy_price"):
        if current_price < t["price_5y"]:
            st.error(f"🔴 **深度便宜**：現價 {current_price:,.0f} 低於 5 年回收價 {t['price_5y']:,.0f}，"
                     f"連年化 14.9% 的積極要求都滿足。", icon="🔥")
        elif current_price < t["buy_price"]:
            st.error(f"🔴 **便宜——低於買進價**：現價 {current_price:,.0f} < 買進價 {t['buy_price']:,.0f}"
                     f"（隱含年化報酬 ≥ 7.2%）。", icon="📈")
        elif current_price < t["sell_price"]:
            st.warning(f"🟡 **持有區間**：現價 {current_price:,.0f} 介於買進價 {t['buy_price']:,.0f} 與"
                       f"賣出目標 {t['sell_price']:,.0f} 之間。等便宜再買、到目標再賣。")
        else:
            st.success(f"🟢 **已達賣出目標**：現價 {current_price:,.0f} ≥ 賣出目標 {t['sell_price']:,.0f}，"
                       f"未來 20 年價值已被反映，賺的是「別人願意付更貴」的錢。")

    # ── 20 年累計價值曲線 ──
    rows = t["rows"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[r["年"] for r in rows], y=[r["企業價值累計(元)"] for r in rows],
                             mode="lines+markers", name="累計企業價值（淨值＋折現）",
                             line=dict(color="#BA7517", width=2)))
    for n, label, color in ((5, "5年回收", "#d62728"), (10, "★買進價", "#d62728"), (20, "賣出目標", "#0a9e6e")):
        r = rows[n - 1]
        fig.add_annotation(x=n, y=r["企業價值累計(元)"], text=f"{label} {r['企業價值累計(元)']:,.0f}",
                           showarrow=True, arrowhead=2, ax=0, ay=-28, font=dict(color=color, size=12))
    if current_price:
        fig.add_hline(y=current_price, line_dash="dash", line_color="#555",
                      annotation_text=f"現價 {current_price:,.0f}", annotation_position="bottom right")
    fig.update_layout(title="未來 20 年累計折現價值 vs 現價",
                      xaxis_title="第 N 年（回收年數）", yaxis_title="每股價值（元）",
                      height=380, margin=dict(t=48, b=8), showlegend=False)
    st.plotly_chart(fig, width="stretch")

    # ── 明細（不可用 expander：本區塊已在外層 expander 內，Streamlit 不允許巢狀）──
    st.markdown("**📋 計算明細**")
    d1, d2 = st.columns(2)
    d1.markdown("**各年 ROE（EPS ÷ 年底每股淨值）**")
    d1.dataframe(pd.DataFrame(inputs["roe_rows"]).rename(
        columns={"year": "年度", "eps": "EPS", "bvps": "每股淨值", "roe_pct": "ROE %"}),
        hide_index=True, width="stretch")
    d2.markdown("**各年盈餘分配率（現金股利 ÷ EPS）**")
    d2.dataframe(pd.DataFrame(inputs["payout_rows"]).rename(
        columns={"year": "年度", "cash_div": "現金股利", "payout_pct": "分配率 %"}),
        hide_index=True, width="stretch")
    st.markdown("**20 年折現表**（前 10 年成長率全速、11~20 年減半——書中台積電表 4 做法）")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    for n in inputs.get("notes", []):
        st.caption(f"⚠️ {n}")
    if inputs["growth_pct"] > 25:
        st.caption("⚠️ 盈餘成長率 >25%，長期維持高成長不易；後 10 年減半已內建，但仍建議搭配較高風險貼水檢視。")
    st.caption("⚠️ 價格需隨最新財報與聯準會利率政策滾動調整；本計算為公開資料推算，非投資建議。")

    return t


def show_cash_return(sid: str, current_price: Optional[float]):
    """財務比率法之首：現金報酬率（孫慶龍評為 5 種比率法中最好）。"""
    st.markdown("## 💰 現金報酬率（財務比率法・作者首選）")
    st.caption("**現金報酬率 = (自由現金流量＋利息費用) ÷ 完全持有企業的財務成本（市值＋長期負債−現金）**。"
               "最理想的企業：每年源源不絕賺現金、又不需要一直投入資本支出。比率愈高愈好，可跨個股排名縮小選股範圍。"
               "書中範例：新普 2013 年算出 8.92%，其後 10 年含股利年化報酬約 13%。")

    cr = _cash_return_cached(sid, current_price) if current_price else None
    if not cr:
        st.info("現金流量或資產負債表資料不足，無法計算現金報酬率。")
        return
    if cr.get("error"):
        st.info(f"現金報酬率不適用：{cr['error']}")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("現金報酬率", f"{cr['cash_return_pct']:.2f}%",
              help=f"現金報酬率（Cash Return）＝(自由現金流量FCF {cr['fcf_ttm']/1e8:,.0f} 億＋利息費用 "
                   f"{(cr['interest_ttm'] or 0)/1e8:,.0f} 億) ÷ 完全持有企業的財務成本 {cr['cost']/1e8:,.0f} 億。{cr['basis']}")
    c2.metric("自由現金流量 FCF（近四季）", f"{cr['fcf_ttm']/1e8:,.0f} 億",
              help="自由現金流量 FCF（Free Cash Flow）＝營業活動現金流 − 資本支出。"
                   "FCF 成長往往是盈餘成長的先行指標。")
    c3.metric("完全持有企業的財務成本", f"{cr['cost']/1e8:,.0f} 億",
              help=f"市值 {cr['mcap']/1e8:,.0f} 億 ＋ 長期負債(含公司債) {cr['lt_debt']/1e8:,.0f} 億 "
                   f"− 現金 {cr['cash']/1e8:,.0f} 億（IFRS：3個月以上定存不算現金）。")
    if cr["cash_return_pct"] >= 10:
        tag, txt = "🔴 強", "高於一般要求報酬（≒折現率），現金創造力強"
    elif cr["cash_return_pct"] >= 5:
        tag, txt = "🟡 中等", "高於無風險利率、低於一般要求報酬"
    else:
        tag, txt = "🟢 偏低", "低於 5%，用現金角度看不便宜"
    c4.metric("解讀", tag,
              help="對照基準：≥10% 現金創造力強（超過一般要求報酬）；5%~10% 中等（高於無風險利率）；"
                   "<5% 從現金角度看不便宜。跨個股比較更有意義。")
    st.caption(f"{tag}：{txt}")


def _pe_panel(title: str, tp: dict, current_price: float, help_eps: str):
    """渲染一組 P/E 三檔目標價（保守/中性/樂觀）+ 對現價的上漲空間。"""
    if not tp:
        st.info(f"{title}：資料不足，無法計算。")
        return
    mults = tp.get("multiples", {})
    st.markdown(f"**{title}**　<span style='color:#888'>（{tp.get('source','')}）</span>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    for col, key, label in (
        (c1, "conservative", "保守"),
        (c2, "neutral", "中性"),
        (c3, "optimistic", "樂觀"),
    ):
        target = tp.get(key)
        m = mults.get(key)
        up = _upside(target, current_price)
        col.metric(
            f"{label}目標價 ×{m}",
            f"{target:,.0f}" if target else "—",
            f"{up:+.1f}%" if up is not None else None,
            delta_color="inverse",  # 台股慣例：上漲空間為正→紅
            help=f"{label}估價 = 預估EPS × {m}倍（{m} 倍 = {tp.get('source','')}）。"
                 f"{help_eps}　漲跌幅 = 目標價 ÷ 現價 − 1。",
        )


# ══════════════════════════════════════════════════════════════════════════
# 估值總覽：六法同一把尺（光譜圖 ＋ 比較表 ＋ 體質檢查）
# ══════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def _mdv_report_cached(sid: str, current_price: float):
    return mdv.generate_valuation_report(sid, current_price)


def show_valuation_overview(sid: str, current_price: Optional[float]):
    """估值分頁頂部總覽：所有估值法的目標價放在同一把價格尺上直接比較。
    回傳 mdv 報告 dict，供下方明細區重用（避免重算）。"""
    st.markdown("## 🎯 估值總覽——六法同一把尺")

    with st.spinner("彙整各估值法（FinMind 財報/現金流/同業 + 知識庫投顧報告）…"):
        rep = _mdv_report_cached(sid, current_price)
        inputs = _dcf_inputs_cached(sid)
        cr = _cash_return_cached(sid, current_price) if current_price else None

    # DCF 用「明細區滑桿」目前的值（第一次載入用預設 4.5% + 10%）
    rf = st.session_state.get(f"dcf_rf_{sid}", 4.5)
    prem = st.session_state.get(f"dcf_prem_{sid}", 10.0)
    dcf = None
    if inputs and not inputs.get("error"):
        dcf = sun_dcf.dcf_table(inputs, risk_free_pct=rf, risk_premium_pct=prem)

    # ── 收集各方法目標價：(方法, 在算什麼, 目標價, 區間下限, 區間上限) ──
    rows = []
    if dcf and dcf.get("buy_price"):
        rows.append(("現金流量折現DCF 買進價（10年回收）", "內在價值＝每股淨值＋20年EPS折現",
                     dcf["buy_price"], dcf.get("price_5y"), dcf.get("sell_price")))
    th = rep.get("targets", {}).get("pe_historical")
    if th and th.get("neutral"):
        rows.append(("本益比P/E（自家歷史）中性", "預估EPS×自己過去3年P/E中位數",
                     th["neutral"], th.get("conservative"), th.get("optimistic")))
    ti = rep.get("targets", {}).get("pe_industry")
    if ti and ti.get("neutral"):
        rows.append(("本益比P/E（同業）中性", "預估EPS×同產業P/E中位數",
                     ti["neutral"], ti.get("conservative"), ti.get("optimistic")))
    peg = rep.get("targets", {}).get("peg")
    if peg and peg.get("fair_price"):
        rows.append(("本益成長比PEG＝1 公允價", "預估EPS×EPS年增率（林區）", peg["fair_price"], None, None))
    adv = rep.get("advisor_analysis", {})
    if adv.get("avg_target_price"):
        rows.append(("投顧平均目標價", "法人共識（知識庫報告平均）", adv["avg_target_price"], None, None))

    if not rows or not current_price:
        st.info("目標價資料不足（可能缺預估 EPS 或現價），無法繪製估值總覽。")
        return rep

    rows.sort(key=lambda r: r[2])

    # ── 光譜圖：橫軸股價、每法一列，紅=現價低於目標(買進)、綠=偏貴 ──
    _RED, _GREEN, _BLUE = "#d62728", "#0a9e6e", "#185FA5"
    fig = go.Figure()
    for name, _, tgt, lo, hi in rows:
        cheap = current_price < tgt
        if lo and hi:
            fig.add_trace(go.Scatter(
                x=[lo, hi], y=[name, name], mode="lines",
                line=dict(color="#bbb", width=5), opacity=0.45,
                hovertemplate=f"{name} 區間 {lo:,.0f} ~ {hi:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=[tgt], y=[name], mode="markers+text",
            marker=dict(size=13, color=_RED if cheap else _GREEN),
            text=[f"{tgt:,.0f}"], textposition="top center",
            textfont=dict(size=11, color=_RED if cheap else _GREEN),
            hovertemplate=f"{name}：{tgt:,.0f} 元<extra></extra>"))
    if dcf and dcf.get("buy_price") and dcf.get("sell_price"):
        fig.add_vrect(x0=0, x1=dcf["buy_price"], fillcolor="rgba(214,39,40,0.06)", line_width=0)
        fig.add_vrect(x0=dcf["sell_price"], x1=max(r[2] for r in rows) * 1.15,
                      fillcolor="rgba(10,158,110,0.07)", line_width=0)
    fig.add_vline(x=current_price, line_dash="dash", line_color=_BLUE, line_width=2)
    fig.add_annotation(x=current_price, y=1.06, yref="paper", showarrow=False,
                       text=f"<b>現價 {current_price:,.0f}</b>", font=dict(color=_BLUE, size=13))
    xmin = min([r[2] for r in rows] + [r[3] for r in rows if r[3]] + [current_price])
    xmax = max([r[2] for r in rows] + [r[4] for r in rows if r[4]] + [current_price])
    pad = (xmax - xmin) * 0.1 or xmax * 0.05
    fig.update_layout(
        height=90 + 52 * len(rows), showlegend=False,
        xaxis=dict(title="股價（元）", range=[xmin - pad, xmax + pad]),
        yaxis=dict(categoryorder="array", categoryarray=[r[0] for r in rows]),
        margin=dict(t=36, b=8, l=8, r=8))
    st.plotly_chart(fig, width="stretch")
    st.caption("🔴 目標價高於現價＝該法看便宜（可買）　🟢 低於現價＝該法看偏貴　"
               "灰色橫帶＝該法的保守~樂觀區間　背景紅區＝低於 DCF 買進價、綠區＝高於 DCF 賣出目標")

    # ── 比較表 ──
    df_rows = []
    for name, what, tgt, lo, hi in rows:
        up = _upside(tgt, current_price)
        df_rows.append({
            "估值法": name,
            "計算方法": what,
            "目標價": f"{tgt:,.0f}",
            "區間（保守~樂觀）": f"{lo:,.0f} ~ {hi:,.0f}" if (lo and hi) else "—",
            "對現價": f"{up:+.1f}%",
            "信號": "🔴 買進" if current_price < tgt else "🟢 偏貴",
        })
    st.dataframe(pd.DataFrame(df_rows), hide_index=True, width="stretch")
    st.caption("縮寫對照：DCF＝現金流量折現法　P/E＝本益比　PEG＝本益成長比　EPS＝每股盈餘　"
               "P/CF＝股價現金流比　FCF＝自由現金流量　ROE＝股東權益報酬率。完整公式見下方各明細區的 ❓。")

    # ── 體質檢查 ＋ 綜合判定 ──
    n_buy = sum(1 for r in rows if current_price < r[2])
    n_exp = len(rows) - n_buy
    health = []
    if cr and cr.get("cash_return_pct") is not None:
        health.append(f"現金報酬率 {cr['cash_return_pct']:.2f}%")
    pcf = rep.get("pcf")
    if pcf and pcf.get("current_pcf"):
        health.append(f"股價現金流比P/CF {pcf['current_pcf']}")
    if dcf and dcf.get("sell_price"):
        health.append(f"現金流量折現DCF 賣出目標 {dcf['sell_price']:,.0f}"
                      f"（{'✅ 已達' if current_price >= dcf['sell_price'] else '未達'}）")
    verdict = f"**綜合判定：{len(rows)} 法中 {n_buy} 法看買進、{n_exp} 法看偏貴**"
    if n_buy > n_exp:
        st.error(verdict + "——多數方法認為現價便宜。", icon="📈")
    elif n_exp > n_buy:
        st.success(verdict + "——多數方法認為現價偏貴。")
    else:
        st.warning(verdict + "——多空各半，看你採信哪套邏輯。")
    if health:
        st.caption("體質檢查（不產生目標價）：" + "　·　".join(health) +
                   f"　·　DCF 參數：折現率 {rf + prem:.1f}%（可在下方 DCF 區調整，總覽即時連動）")
    return rep


def show_multidim_valuation(sid: str, current_price: float, advisor_reports: list = None,
                            extra_targets: list = None, rep: dict = None):
    """財務比率法多維度估值：孫慶龍8步驟預估EPS × (歷史P/E + 同業P/E) + PEG + P/CF + 投顧反推。
    股價 < 目標價 = 買進訊號。每個數字皆有 ❓ 說明，且全部來自真實資料。
    extra_targets: [(名稱, 目標價), ...] 額外納入最後的目標價彙整表（例如 DCF 買進價）。"""
    st.markdown("## 💎 財務比率法：多維度目標價")
    st.caption("核心：孫慶龍 8 步驟法的『預估EPS』。再用 P/E（兩個基準：自家歷史＋同業）、PEG、P/CF "
               "多角度算目標價，並與投顧報告反推對照。**股價 < 中性目標價 = 買進**。所有數字 hover ❓ 看算法。")

    if rep is None:
        with st.spinner("彙整真實資料（FinMind 財報/現金流/同業 + 知識庫投顧報告）…"):
            rep = mdv.generate_valuation_report(sid, current_price, advisor_reports)

    est_eps = rep.get("est_eps")
    if not est_eps:
        st.error("無法取得預估EPS（可能缺財報或 EPS 為負），多維度估值無法進行。")
        if rep.get("fundamental", {}).get("errors"):
            st.caption("； ".join(rep["fundamental"]["errors"]))
        return rep

    help_eps = (f"預估EPS {est_eps} 元來自孫慶龍8步驟法（本頁上方明細），屬『預估值』，"
                f"與投顧的預估可能不同——目標價會隨此 EPS 等比例變動。")

    # ── 頂部：核心指標 ────────────────────────────────────────────────
    fwd_per = rep.get("current_per")
    growth = rep.get("growth", {})
    a, b, c, d = st.columns(4)
    a.metric("預估每股盈餘 EPS（孫慶龍）", f"{est_eps:.2f} 元",
             help=VALUATION_HELP["eps_forecast"])
    b.metric("現價", f"{current_price:,.0f} 元" if current_price else "—",
             help="最新收盤價，買賣信號的比較基準。")
    c.metric("預估本益比 P/E（用預估EPS）", f"{fwd_per:.1f}" if fwd_per else "—",
             help="本益比 P/E（Price/Earnings）＝現價 ÷ 預估每股盈餘EPS。與下方『本益比河流圖』"
                  "用近四季TTM實際EPS 算的當前本益比不同，這是看『未來』的便宜度。")
    g = growth.get("growth_for_peg")
    d.metric("真實每股盈餘EPS年增率", f"{g:+.1f}%" if g is not None else "—",
             help=f"每股盈餘EPS年增率＝(預估EPS ÷ 最近完整年度實際EPS − 1)×100%。"
                  f"取代過去亂編的數字，改用真實資料：{growth.get('basis','—')}")

    # ── 買賣信號 ──────────────────────────────────────────────────────
    if rep.get("signal"):
        # 台股慣例：買進=紅（st.error 紅框）、偏貴=綠（st.success 綠框）
        (st.error(f"**綜合信號**：{rep['signal']}　<small>（以自家歷史 P/E 中性目標為準；目標價依賴上述預估EPS）</small>",
                  icon="📈") if "買進" in rep["signal"]
         else st.success(f"**綜合信號**：{rep['signal']}"))

    st.divider()

    # ── P/E 兩個基準 ──────────────────────────────────────────────────
    st.markdown("### 📐 P/E 本益比目標價（兩個基準）")
    _pe_panel("① 本益比P/E・自家歷史（這檔過去3年每日本益比的20/50/80百分位）",
              rep["targets"].get("pe_historical"), current_price, help_eps)
    st.write("")
    _pe_panel("② 本益比P/E・同業（FinMind 同產業樣本的25/50/75百分位）",
              rep["targets"].get("pe_industry"), current_price, help_eps)
    ind = rep.get("industry_basis")
    if ind:
        st.caption(f"同業基準：{ind['source']}　｜　Goodinfo 同業頁伺服器端被反爬封鎖，故改用 FinMind 真實 P/E 計算。")

    st.divider()

    # ── PEG ──────────────────────────────────────────────────────────
    st.markdown("### 📊 PEG 本益成長比")
    peg = rep["targets"].get("peg")
    if peg:
        pcols = st.columns(3)
        cur_peg = peg.get("current_peg")
        interp = "—"
        if cur_peg is not None:
            if cur_peg < 0.8:
                interp = "🔴 極度低估"
            elif cur_peg < 1.0:
                interp = "🔴 低估"
            elif cur_peg <= 1.5:
                interp = "🟡 合理"
            else:
                interp = "🟢 昂貴"
        pcols[0].metric("當前本益成長比 PEG", f"{cur_peg}" if cur_peg is not None else "—",
                        help=VALUATION_HELP["peg"] + f"　當前＝預估本益比({fwd_per}) ÷ EPS年增率({peg.get('growth_pct')}%)")
        pcols[1].metric("PEG 解讀", interp, help="本益成長比 PEG 越低越划算（成長相對於估值便宜）。")
        if peg.get("fair_price"):
            up = _upside(peg["fair_price"], current_price)
            pcols[2].metric("PEG=1 公允價", f"{peg['fair_price']:,.0f}",
                            f"{up:+.1f}%" if up is not None else None,
                            delta_color="inverse",
                            help=f"Peter Lynch：PEG=1 時公允P/E=年增率({peg['fair_pe']})，公允價=預估EPS×年增率。{help_eps}")
        else:
            pcols[2].metric("PEG=1 公允價", "不適用",
                            help=peg.get("note") or "成長率過高/過低，PEG 公允價失真，僅看當前 PEG。")
        if peg.get("note"):
            st.caption(f"⚠️ {peg['note']}")
    else:
        st.info("PEG：缺真實年增率（需至少一個完整年度 EPS）或成長率非正，無法計算。")

    st.divider()

    # ── P/CF ─────────────────────────────────────────────────────────
    st.markdown("### 💧 股價現金流比 P/CF（本流法・現金流檢查）")
    pcf = rep.get("pcf")
    if pcf:
        fps = pcf.get("fcf_per_share")
        f1, f2, f3 = st.columns(3)
        f1.metric("每股自由現金流 FCF", f"{fps:.2f} 元" if fps is not None else "—",
                  help=VALUATION_HELP["pcf"])
        f2.metric("當前股價現金流比 P/CF", f"{pcf['current_pcf']}" if pcf.get("current_pcf") else "不適用",
                  help="股價現金流比 P/CF＝股價 ÷ 每股自由現金流FCF。越低代表每元現金流越便宜；FCF 為負則不適用。")
        op = pcf.get("op_cf_ttm")
        f3.metric("近四季營業現金流", f"{op/1e8:,.0f} 億" if op is not None else "—",
                  help="近四季營業活動現金流（已將FinMind的YTD累計還原單季再加總）。")
        if pcf.get("note"):
            st.caption(f"⚠️ {pcf['note']}")
    else:
        st.info("P/CF：現金流量資料不足，無法計算。")

    st.divider()

    # ── 投顧報告反推 ──────────────────────────────────────────────────
    st.markdown("### 🏦 投顧報告目標價（反推隱含本益比 P/E）")
    adv = rep.get("advisor_analysis", {})
    if adv.get("count"):
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("投顧平均目標價", f"{adv['avg_target_price']:,.0f}",
                   f"{_upside(adv['avg_target_price'], current_price):+.1f}%" if current_price else None,
                   delta_color="inverse",
                   help="知識庫所有投顧報告目標價的平均。")
        ac2.metric("反推平均隱含本益比 P/E", f"{adv['avg_pe']}" if adv.get("avg_pe") else "—",
                   help=VALUATION_HELP["advisor_pe"])
        ac3.metric("報告數", f"{adv['count']} 份", help="知識庫 投顧報告/ 資料夾中成功解析的報告數。")
        rows = []
        for v in adv["details"]:
            rows.append({
                "券商": v["source"],
                "日期": v.get("date") or "—",
                "目標價": v["target_price"],
                "預估每股盈餘EPS": v.get("est_eps"),
                "EPS來源": v.get("eps_src"),
                "隱含本益比P/E": v.get("pe"),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("隱含本益比P/E = 目標價 ÷ 預估每股盈餘EPS。『EPS來源=孫慶龍』代表報告沒寫EPS，改用我們的預估EPS反推。")
    else:
        st.info("知識庫尚無可解析的投顧報告（路徑：知識庫/個股/<代號>_<名稱>/投顧報告/<券商>_<日期>.md）。")

    # ── 全部目標價彙整對照 ────────────────────────────────────────────
    st.divider()
    st.markdown("### 🎯 目標價彙整對照（股價 < 目標價 = 買進）")
    summary_rows = []
    th = rep["targets"].get("pe_historical")
    ti = rep["targets"].get("pe_industry")
    if th:
        summary_rows.append(("本益比P/E（自家歷史）中性", th.get("neutral")))
    if ti:
        summary_rows.append(("本益比P/E（同業）中性", ti.get("neutral")))
    if peg and peg.get("fair_price"):
        summary_rows.append(("本益成長比PEG=1 公允價", peg["fair_price"]))
    if adv.get("avg_target_price"):
        summary_rows.append(("投顧平均", adv["avg_target_price"]))
    for name, t in (extra_targets or []):
        if t:
            summary_rows.append((name, t))
    if summary_rows:
        df_rows = []
        for name, t in summary_rows:
            up = _upside(t, current_price)
            df_rows.append({
                "估值法": name,
                "目標價": f"{t:,.0f}" if t else "—",
                "對現價": f"{up:+.1f}%" if up is not None else "—",
                "信號": ("🔴 買進" if (t and current_price and current_price < t)
                         else "🟢 偏貴" if t else "—"),
            })
        st.dataframe(pd.DataFrame(df_rows), width="stretch", hide_index=True)
    st.caption("⚠️ 自家目標價會隨『預估EPS』等比例變動；本頁為公開資料推算，非投資建議。")

    return rep