"""估值分析展示元件
帶小問號說明每個計算怎麼算出來的
"""
import streamlit as st
import pandas as pd
from datetime import date
from typing import Dict, Optional

from src.analysis import multidim_valuation as mdv
from src.analysis import fundamental_forecast as ff


# 名詞解釋（供 st.metric 的 help= 用，hover 即顯示小問號 ❓）
VALUATION_HELP = {
    "peg": "PEG = 本益比 ÷ EPS年增率(%)。<0.8 極度低估、0.8-1.0 低估、1.0-1.5 合理、>1.5 昂貴。"
           "本系統年增率用『真實資料』：預估EPS(孫慶龍) vs 最近完整年度實際EPS。",
    "pcf": "P/CF（本流法）= 股價 ÷ 每股自由現金流(FCF)。FCF = 近四季營業現金流 − 資本支出。"
           "檢查獲利是否有現金支撐；FCF 為負代表暫無現金支撐，本流法不適用。",
    "advisor_pe": "從投顧報告反推：目標價 ÷ 預估EPS = 隱含P/E。優先用報告自己的預估EPS，"
                  "沒有就用我們孫慶龍的預估EPS（會標示）。多家取平均。",
    "eps_forecast": "預估EPS來自孫慶龍8步驟法：①今年累積營收YoY ②去年全年營收 ③預估營收 "
                    "④近四季母公司淨利率 ⑤預估淨利 ⑥÷發行股數。這是『預估值』，與投顧預估可能不同。",
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
            f"①累積營收YoY" + _help_icon("eps_forecast"),
            f"{yoy:+.1f}%" if yoy else "—",
            help="今年前N月 vs 去年同期的累積營收增速"
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
            "④近四季淨利率" + _help_icon("eps_forecast"),
            f"{net_margin}%" if net_margin else "—",
            help="近四季EPS×股數÷近四季營收（近四季＝近12個月，英文 TTM）"
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
            "⑥預估EPS" + _help_icon("eps_forecast"),
            f"{est_eps:.2f}元" if est_eps else "—",
            help="預估淨利 ÷ 發行股數"
        )

    with col7:
        payout_ratio = result.get("payout_ratio_avg_pct")
        st.metric(
            "⑦平均分配率" + _help_icon("eps_forecast"),
            f"{payout_ratio:.1f}%" if payout_ratio else "—",
            help="近三年 (現金股利÷EPS) 平均值"
        )

    with col8:
        est_div = result.get("est_dividend")
        st.metric(
            "⑧預估現金股利" + _help_icon("eps_forecast"),
            f"{est_div:.2f}元" if est_div else "—",
            help="預估EPS × 分配率"
        )

    # 顯示摘要
    if result.get("errors"):
        st.warning(f"⚠️ 計算提醒：{'; '.join(result['errors'])}")

    return result


def _upside(target, price):
    if not target or not price:
        return None
    return (target / price - 1) * 100


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


def show_multidim_valuation(sid: str, current_price: float, advisor_reports: list = None):
    """多維度企業估值：孫慶龍8步驟預估EPS × (歷史P/E + 同業P/E) + PEG + P/CF + 投顧反推。
    股價 < 目標價 = 買進訊號。每個數字皆有 ❓ 說明，且全部來自真實資料。"""
    st.markdown("## 💎 多維度企業估值")
    st.caption("核心：孫慶龍 8 步驟法的『預估EPS』。再用 P/E（兩個基準：自家歷史＋同業）、PEG、P/CF "
               "多角度算目標價，並與投顧報告反推對照。**股價 < 中性目標價 = 買進**。所有數字 hover ❓ 看算法。")

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
    a.metric("預估EPS（孫慶龍）", f"{est_eps:.2f} 元",
             help=VALUATION_HELP["eps_forecast"])
    b.metric("現價", f"{current_price:,.0f} 元" if current_price else "—",
             help="最新收盤價，買賣信號的比較基準。")
    c.metric("預估本益比（用預估EPS）", f"{fwd_per:.1f}" if fwd_per else "—",
             help="現價 ÷ 預估EPS。與下方『本益比河流圖』用近四季(TTM)實際EPS 算的當前本益比不同，這是看『未來』的便宜度。")
    g = growth.get("growth_for_peg")
    d.metric("真實EPS年增率", f"{g:+.1f}%" if g is not None else "—",
             help=f"取代過去亂編的數字，改用真實資料：{growth.get('basis','—')}")

    # ── 買賣信號 ──────────────────────────────────────────────────────
    if rep.get("signal"):
        # 台股慣例：買進=紅（st.error 紅框）、偏貴=綠（st.success 綠框）
        (st.error(f"**綜合信號**：{rep['signal']}　<small>（以自家歷史 P/E 中性目標為準；目標價依賴上述預估EPS）</small>",
                  icon="📈") if "買進" in rep["signal"]
         else st.success(f"**綜合信號**：{rep['signal']}"))

    st.divider()

    # ── P/E 兩個基準 ──────────────────────────────────────────────────
    st.markdown("### 📐 P/E 本益比目標價（兩個基準）")
    _pe_panel("① 自家歷史 P/E（這檔過去3年每日P/E的20/50/80百分位）",
              rep["targets"].get("pe_historical"), current_price, help_eps)
    st.write("")
    _pe_panel("② 同業 P/E（FinMind 同產業樣本的25/50/75百分位）",
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
        pcols[0].metric("當前 PEG", f"{cur_peg}" if cur_peg is not None else "—",
                        help=VALUATION_HELP["peg"] + f"　當前 = forward P/E({fwd_per}) ÷ 年增率({peg.get('growth_pct')}%)")
        pcols[1].metric("PEG 解讀", interp, help="PEG 越低越划算（成長相對於估值便宜）。")
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
    st.markdown("### 💧 P/CF 本流法（現金流檢查）")
    pcf = rep.get("pcf")
    if pcf:
        fps = pcf.get("fcf_per_share")
        f1, f2, f3 = st.columns(3)
        f1.metric("每股自由現金流 FCF", f"{fps:.2f} 元" if fps is not None else "—",
                  help=VALUATION_HELP["pcf"])
        f2.metric("當前 P/CF", f"{pcf['current_pcf']}" if pcf.get("current_pcf") else "不適用",
                  help="股價 ÷ 每股FCF。越低代表每元現金流越便宜；FCF 為負則不適用。")
        op = pcf.get("op_cf_ttm")
        f3.metric("近四季營業現金流", f"{op/1e8:,.0f} 億" if op is not None else "—",
                  help="近四季營業活動現金流（已將FinMind的YTD累計還原單季再加總）。")
        if pcf.get("note"):
            st.caption(f"⚠️ {pcf['note']}")
    else:
        st.info("P/CF：現金流量資料不足，無法計算。")

    st.divider()

    # ── 投顧報告反推 ──────────────────────────────────────────────────
    st.markdown("### 🏦 投顧報告目標價（反推隱含 P/E）")
    adv = rep.get("advisor_analysis", {})
    if adv.get("count"):
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("投顧平均目標價", f"{adv['avg_target_price']:,.0f}",
                   f"{_upside(adv['avg_target_price'], current_price):+.1f}%" if current_price else None,
                   delta_color="inverse",
                   help="知識庫所有投顧報告目標價的平均。")
        ac2.metric("反推平均隱含 P/E", f"{adv['avg_pe']}" if adv.get("avg_pe") else "—",
                   help=VALUATION_HELP["advisor_pe"])
        ac3.metric("報告數", f"{adv['count']} 份", help="知識庫 投顧報告/ 資料夾中成功解析的報告數。")
        rows = []
        for v in adv["details"]:
            rows.append({
                "券商": v["source"],
                "日期": v.get("date") or "—",
                "目標價": v["target_price"],
                "預估EPS": v.get("est_eps"),
                "EPS來源": v.get("eps_src"),
                "隱含P/E": v.get("pe"),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("隱含P/E = 目標價 ÷ 預估EPS。『EPS來源=孫慶龍』代表報告沒寫EPS，改用我們的預估EPS反推。")
    else:
        st.info("知識庫尚無可解析的投顧報告（路徑：知識庫/個股/<代號>_<名稱>/投顧報告/<券商>_<日期>.md）。")

    # ── 全部目標價彙整對照 ────────────────────────────────────────────
    st.divider()
    st.markdown("### 🎯 目標價彙整對照（股價 < 目標價 = 買進）")
    summary_rows = []
    th = rep["targets"].get("pe_historical")
    ti = rep["targets"].get("pe_industry")
    if th:
        summary_rows.append(("自家歷史P/E 中性", th.get("neutral")))
    if ti:
        summary_rows.append(("同業P/E 中性", ti.get("neutral")))
    if peg and peg.get("fair_price"):
        summary_rows.append(("PEG=1 公允價", peg["fair_price"]))
    if adv.get("avg_target_price"):
        summary_rows.append(("投顧平均", adv["avg_target_price"]))
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