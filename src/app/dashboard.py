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
from src.analysis import technical as tech_mod
from src.analysis.valuation import pe_band
from src.app import valuation_display as vdisp
from src.utils import read_reports
from src.data import finmind_client as fm
from src.data import gemini_client as gem
from src.data import analysts as analysts_mod
from src.data import news_sources
from src.data import watchlist
from src.data.snapshot import build_snapshot
from src.data import theme_data as td

# 投顧/法人相關新聞的過濾關鍵字（MoneyDJ 免費研究報告區已停更至 2011，改用新聞過濾）
ANALYST_KEYWORDS = [
    "目標價", "評等", "調升", "調降", "上修", "下修", "升評", "降評", "外資", "投顧",
    "加碼", "減碼", "買進", "賣出", "中立", "看好", "出具", "報告", "喊", "上調", "下調",
    "大摩", "小摩", "摩根", "高盛", "瑞銀", "美林", "花旗", "野村", "瑞信", "麥格理",
]

# 「關鍵數據」過濾用：標題同時含這些字＋數字才算與投資數據相關（投顧動向分頁用，去雜訊）
_KEY_DATA_TERMS = (
    "目標價", "上看", "上修", "下修", "調升", "調降", "升評", "降評", "評等",
    "目標", "EPS", "每股", "毛利", "營收", "獲利", "買超", "賣超", "增持",
    "減持", "上調", "下調", "看好", "看壞", "本益比",
)

st.set_page_config(page_title="StockBrain Radar", page_icon="📡", layout="wide")

# 名詞解釋（滑鼠移到 ? 會顯示）
HELP = {
    "per": "本益比 PER（Price/Earnings）= 股價 ÷ 每股盈餘。市場願意為每 1 元獲利付多少錢，越高代表估值越貴。",
    "pbr": "股價淨值比 PBR（Price/Book）= 股價 ÷ 每股淨值。<1 代表股價低於帳面價值。",
    "peg": "本益成長比 PEG（P/E to Growth）= 本益比 ÷ 每股盈餘EPS年增率(%)。成長股看 PEG：<1 偏便宜、1~2 合理、>2 偏貴。",
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
    "river": "本益比河流圖：彩色帶＝各本益比倍數 ×（近四季每股盈餘EPS）對應的股價。黑線（收盤價）落在低帶＝便宜、落在高帶＝貴。EPS 以季底估算，故換季時帶會跳動。",
}


@st.cache_data(ttl=3600)
def _snapshot(sid: str):
    return build_snapshot(sid)


@st.cache_data(ttl=3600)
def _inst(sid: str):
    # FinMind 額度用罄會回 402；失敗回空表，呼叫端 `if not inst.empty` 會自然略過。
    try:
        df = fm.institutional_investors(sid, days=45)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.sort_values("date")


@st.cache_data(ttl=3600)
def _pe_band(sid: str):
    return pe_band(sid)


@st.cache_data(ttl=3600)
def _margin_short(sid: str):
    """融資融券餘額時序（張）：融資=MarginPurchaseTodayBalance、融券=ShortSaleTodayBalance。

    FinMind 此資料集在匿名/額度用罄時會回 402；單一次要數據失敗不該炸掉整個分頁，
    遇任何錯誤回 None，呼叫端會優雅略過。
    """
    try:
        df = fm.margin_short(sid, days=90)
    except Exception:
        return None
    if df is None or df.empty:
        return df
    df = df.sort_values("date").copy()
    df["融資餘額"] = df["MarginPurchaseTodayBalance"]
    df["融券餘額"] = df["ShortSaleTodayBalance"]
    return df


@st.cache_data(ttl=86400)
def _name(sid: str):
    return fm.stock_name(sid)


@st.cache_data(ttl=86400)
def _company_profile(sid: str):
    """用 Gemini 生成『這間公司在做什麼』白話簡介，快取一天（省 token）。沒設 key 回 None。"""
    if not gem.is_configured():
        return None
    nm = _name(sid) or ""
    prompt = (
        f"用繁體中文，針對台股 {nm}({sid})，條列 4~6 點介紹這間公司實際在『做什麼』："
        f"①一句話定位（做什麼的）②主要產品/業務與各自營收占比（知道就寫）"
        f"③技術或製程強項 ④主要客戶/應用領域 ⑤主要競爭對手。"
        f"白話、精簡、每點一行，不要投資建議、不要估值。"
    )
    try:
        return gem.generate(prompt)
    except Exception:
        return None


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
def _atr(sid: str):
    return tech_mod.calc_atr(sid)


def _resample_ohlc(df, rule):
    """日K → 周/月K：開=首、高=最高、低=最低、收=末、量=加總。"""
    g = df.set_index("date").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum"}).dropna()
    return g.reset_index()


# 各週期均線組（周K 用 13/34/89 費波那契週均線）
_MA_BY_PERIOD = {"日K": [5, 10, 20, 60], "周K": [13, 34, 89], "月K": [5, 10, 20]}


@st.cache_data(ttl=3600)
def _kline(sid: str, period: str):
    """K 線資料（含該週期對應均線）。period: 日K/周K/月K。FinMind 失敗回空表。

    抓取天數放大，確保最長均線（如周K MA89）在顯示的 120 根都有值。
    """
    days = {"日K": 300, "周K": 1700, "月K": 3700}.get(period, 300)
    try:
        df = fm.stock_price(sid, days=days)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "vol"})
    df = df[[c for c in ("date", "open", "high", "low", "close", "vol") if c in df.columns]]
    if period == "周K":
        df = _resample_ohlc(df, "W-FRI")
    elif period == "月K":
        df = _resample_ohlc(df, "ME")
    for n in _MA_BY_PERIOD.get(period, [5, 10, 20, 60]):
        df[f"MA{n}"] = df["close"].rolling(n).mean()
    return df.tail(120).reset_index(drop=True)


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


def _hist_trend_table(records, period_key, value_key, unit="", fmt="{:.2f}", n_show=4):
    """台股資訊網風格橫式數字表：值（台股紅漲綠跌，較前期）＋歷史排名。
    records：完整歷史 list[dict]（時間升冪）。回傳 HTML 字串或 None。"""
    if not records:
        return None
    recs = [r for r in records if r.get(value_key) is not None]
    if not recs:
        return None
    vals = [r[value_key] for r in recs]
    total = len(vals)
    start = max(0, total - n_show)
    th = "".join(
        f"<th style='padding:4px 12px;border-bottom:1px solid #e3e3e3;color:#666;font-weight:600;text-align:right'>{recs[i][period_key]}</th>"
        for i in range(start, total)
    )
    vtd, rtd = "", ""
    for i in range(start, total):
        v = recs[i][value_key]
        prev = recs[i - 1][value_key] if i > 0 else None
        if prev is None or v == prev:
            color, arrow = "#333", ""
        elif v > prev:           # 上升 → 紅（台股慣例）
            color, arrow = UP_RED, " ▲"
        else:                    # 下降 → 綠
            color, arrow = DOWN_GREEN, " ▼"
        vtd += (f"<td style='padding:4px 12px;text-align:right;color:{color};"
                f"font-weight:700;font-size:1.05em'>{fmt.format(v)}{unit}{arrow}</td>")
        rk = sum(1 for x in vals if x > v) + 1
        if rk == 1:
            tag = "🔺 歷史新高"
        elif rk == total:
            tag = "🔻 歷史新低"
        else:
            tag = f"第 {rk} 高／共 {total}"
        rtd += (f"<td style='padding:2px 12px;text-align:right;color:#999;"
                f"font-size:0.78em'>{tag}</td>")
    return (
        "<table style='border-collapse:collapse;margin-top:2px'>"
        f"<tr><th></th>{th}</tr>"
        f"<tr><td style='color:#999;font-size:0.8em;padding-right:6px'>數值</td>{vtd}</tr>"
        f"<tr><td style='color:#999;font-size:0.78em;padding-right:6px'>歷史排名</td>{rtd}</tr>"
        "</table>"
    )


# 台股慣例配色：紅＝上漲/買超、綠＝下跌/賣超
UP_RED = "#d62728"
DOWN_GREEN = "#1ca35a"
NEUTRAL_GRAY = "#808495"
BUYSELL_COLORS = {"買超": UP_RED, "賣超": DOWN_GREEN}


def _flow_metric(col, label, lots, unit="張", help_=None):
    """買賣超流量指標：買超紅▲、賣超綠▼（台股慣例）。help_ 以 HTML title 保留 hover 說明。"""
    tip = f' title="{help_}"' if help_ else ""
    note = " ⓘ" if help_ else ""
    if lots is None:
        col.markdown(
            f'<div style="font-size:0.8rem;color:{NEUTRAL_GRAY}"{tip}>{label}{note}</div>'
            f'<div style="font-size:1.7rem;font-weight:600;color:{NEUTRAL_GRAY}">—</div>',
            unsafe_allow_html=True)
        return
    if lots > 0:
        color, arrow, tag = UP_RED, "▲", "買超"
    elif lots < 0:
        color, arrow, tag = DOWN_GREEN, "▼", "賣超"
    else:
        color, arrow, tag = NEUTRAL_GRAY, "—", "持平"
    col.markdown(
        f'<div style="font-size:0.8rem;color:{NEUTRAL_GRAY}"{tip}>{label}{note}</div>'
        f'<div style="font-size:1.7rem;font-weight:600;color:{color}">'
        f'{arrow} {abs(lots):,.0f} <span style="font-size:1rem">{unit}</span></div>'
        f'<div style="font-size:0.85rem;color:{color}">{tag}</div>',
        unsafe_allow_html=True)


def _pos_red_neg_green(v):
    """表格用：數值為正→紅、負→綠（台股慣例）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return f"color:{UP_RED};font-weight:600"
    if x < 0:
        return f"color:{DOWN_GREEN};font-weight:600"
    return ""


# --- Sidebar ---------------------------------------------------------------
st.sidebar.title("📡 StockBrain Radar")


@st.cache_data(ttl=86400, show_spinner=False)
def _stock_options() -> list[str]:
    """全市場「代號 中文名」清單，供側欄搜尋（打中文名或代號都能過濾）。"""
    try:
        info = fm.all_stock_info()
        info = info[info["stock_id"].astype(str).str.fullmatch(r"\d{4}")]
        info = info.drop_duplicates("stock_id").sort_values("stock_id")
        return [f"{r.stock_id} {r.stock_name}" for r in info.itertuples()]
    except Exception:
        return []


_opts = _stock_options()
_opt_by_sid = {o.split(" ", 1)[0]: o for o in _opts}

# 清單點選 / 市場地圖跳轉：用暫存 key 避免「widget 已渲染後不能改 state」的限制
st.session_state.setdefault("sid_select", _opt_by_sid.get("2330"))
if st.session_state.get("_map_pending_sid"):
    _p = str(st.session_state.pop("_map_pending_sid")).strip()
    st.session_state["sid_select"] = _opt_by_sid.get(_p, f"{_p} {_p}")

if _opts:
    _cur = st.session_state.get("sid_select")
    _options = _opts if (_cur is None or _cur in _opt_by_sid.values()) else [_cur] + _opts
    _choice = st.sidebar.selectbox(
        "股票（輸入中文名或代號搜尋）", _options, key="sid_select",
        help="點一下直接打字即可搜尋：中文（如 台積）或代號（如 2330）都行。")
    sid = _choice.split(" ", 1)[0].strip() if _choice else ""
else:  # FinMind 全市場清單抓不到時退回純代號輸入
    sid = st.sidebar.text_input("股票代號（如 2330）", value="2330").strip()
st.sidebar.caption("資料來源：FinMind / Google News。當日快取，僅供個人研究。")


def _select_sid(s):
    st.session_state["_map_pending_sid"] = s


def _remove_sid(s):
    watchlist.remove(s)


def _move_sid(s, d):
    watchlist.move(s, d)


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
        c1, c2, c3, c4 = st.sidebar.columns([3.4, 0.8, 0.8, 0.8])
        c1.button(f"{_it['name']}({_it['sid']})", key=f"wl_{_it['sid']}",
                  width="stretch", on_click=_select_sid, args=(_it["sid"],))
        c2.button("↑", key=f"up_{_it['sid']}", on_click=_move_sid, args=(_it["sid"], -1),
                  help="往上移")
        c3.button("↓", key=f"dn_{_it['sid']}", on_click=_move_sid, args=(_it["sid"], 1),
                  help="往下移")
        c4.button("✕", key=f"rm_{_it['sid']}", on_click=_remove_sid, args=(_it["sid"],),
                  help="移出清單")
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

# --- 📅 近期重要事件 行事曆（上半大盤 / 下半本檔）------------------------------
import datetime as _dt
_WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
_SKIP_MACRO = {"上月營收公布截止", "季財報公布截止"}  # 移到下半「本檔」區，避免重複


def _fmt_md_wd(iso: str):
    d = _dt.date.fromisoformat(iso)
    return f"{d.month:02d}/{d.day:02d}", _WD[d.weekday()]


@st.cache_data(ttl=3600)
def _macro_events():
    from src.data import macro_data as _md
    try:
        return _md.upcoming_events()
    except Exception:
        return []


@st.cache_data(ttl=3600)
def _stock_specific_events(sid: str):
    # 注意：參數名不可用底線開頭，否則 st.cache_data 會忽略它、所有股票共用同一快取
    from src.data import stock_events as _se
    try:
        return _se.upcoming(sid)
    except Exception:
        return []


_Q_LABEL = {5: "Q1", 8: "Q2", 11: "Q3", 3: "年報"}
_Q_END   = {5: (0, 3, 31), 8: (0, 6, 30), 11: (0, 9, 30), 3: (-1, 12, 31)}  # 截止月 → 該期季底


@st.cache_data(ttl=3600)
def _stock_calendar(sid: str):
    """本檔三大日期：月營收、季財報（法定截止，恆有）、法說會（公告才有，否則未公布）+ 其他個股事件。
    公司若提早公布（截止日前），事件自動打勾並推進到下一期，不對已公布的數據倒數。"""
    from src.data import finmind_client as _fm
    from src.data import macro_data as _md
    today = _dt.date.today()

    def _rev_ym(deadline):  # 10 日前公布的是上個月營收
        return (deadline.year - 1, 12) if deadline.month == 1 else (deadline.year, deadline.month - 1)

    rev = _md._next_monthly(today, 10)
    rev_sub = "每月 10 日前 · 月營收領先指標"
    try:
        _r = _fm.month_revenue(sid, days=100)
        if not _r.empty:
            _last = _r.sort_values(["revenue_year", "revenue_month"]).iloc[-1]
            if (int(_last["revenue_year"]), int(_last["revenue_month"])) >= _rev_ym(rev):
                rev_sub = f"{_rev_ym(rev)[1]} 月已公布 ✅ · 每月 10 日前"
                rev = _md._next_monthly(rev + _dt.timedelta(days=1), 10)
    except Exception:
        pass
    rev_m = _rev_ym(rev)[1]

    fin = _md._next_fin_deadline(today)
    fin_sub = "法定截止日 · 實際多提早"
    try:
        _fs = _fm.financial_statements(sid, days=300)
        if not _fs.empty:
            dy, m, d = _Q_END[fin.month]
            if str(_fs["date"].max())[:10] >= _dt.date(fin.year + dy, m, d).isoformat():
                fin_sub = f"{_Q_LABEL[fin.month]} 已公布 ✅ · 法定截止日"
                fin = _md._next_fin_deadline(fin + _dt.timedelta(days=1))
    except Exception:
        pass
    q = _Q_LABEL.get(fin.month, "財報")

    evs = _stock_specific_events(sid)
    conf = next((e for e in evs if e["name"] == "法說會"), None)
    return {
        "rev": {"date": rev.isoformat(), "days": (rev - today).days,
                "label": f"公布 {rev_m} 月營收", "sub": rev_sub},
        "fin": {"date": fin.isoformat(), "days": (fin - today).days,
                "label": f"公布 {q} 財報", "sub": fin_sub},
        "conf": conf,
        "extras": [e for e in evs if e["name"] != "法說會"],
    }


def _evt_row(label: str, sub: str, date_iso, days):
    if date_iso:
        mmdd, wd = _fmt_md_wd(date_iso)
        daycolor = "color:#BA7517;" if (days is not None and days <= 10) else "opacity:0.55;"
        right = (f"<div style='font-size:16px;font-weight:600'>{mmdd} "
                 f"<span style='font-size:12px;font-weight:400;opacity:0.55'>{wd}</span></div>"
                 f"<div style='font-size:11px;{daycolor}'>還有 {days} 天</div>")
    else:
        right = "<div style='font-size:14px;opacity:0.45'>未公布</div>"
    st.markdown(
        "<div style='display:flex;align-items:center;gap:12px;padding:5px 0'>"
        f"<div style='flex:1'><div style='font-size:14px'>{label}</div>"
        f"<div style='font-size:11px;opacity:0.55'>{sub}</div></div>"
        f"<div style='text-align:right;min-width:84px'>{right}</div></div>",
        unsafe_allow_html=True)


_macro = sorted((e for e in _macro_events() if e["name"] not in _SKIP_MACRO),
                key=lambda e: e["date"])
_cal = _stock_calendar(sid)
with st.container(border=True):
    st.markdown("📅 **近期重要事件**")

    # 上半：大盤 / 總經（日期為主）
    st.caption("大盤 / 總經")
    near = _macro[:5]
    if near:
        for col, e in zip(st.columns(len(near)), near):
            mmdd, wd = _fmt_md_wd(e["date"])
            daycolor = "color:#BA7517;" if e["days"] <= 10 else "opacity:0.55;"
            col.markdown(
                f"<div style='font-size:22px;font-weight:600;line-height:1'>{mmdd}</div>"
                f"<div style='font-size:11px;opacity:0.5;margin:2px 0 5px'>{wd}</div>"
                f"<div style='font-size:13px;line-height:1.3'>{e['name']}</div>"
                f"<div style='font-size:11px;{daycolor}margin-top:4px'>還有 {e['days']} 天</div>",
                unsafe_allow_html=True)
    if len(_macro) > 5:
        rest = "　".join(f"{e['name']} {e['date'][5:]}" for e in _macro[5:])
        st.caption(f"更多：{rest}")

    # 下半：本檔個股（營收 / 財報 / 法說會 + 其他）
    st.divider()
    st.caption(f"本檔 · {_nm}({sid})" if _nm else f"本檔 · {sid}")
    _evt_row(_cal["rev"]["label"], _cal["rev"]["sub"], _cal["rev"]["date"], _cal["rev"]["days"])
    _evt_row(_cal["fin"]["label"], _cal["fin"]["sub"], _cal["fin"]["date"], _cal["fin"]["days"])
    _conf = _cal["conf"]
    _evt_row("法說會", _conf["hint"] if _conf else "尚未公告法說會日期",
             _conf["date"] if _conf else None, _conf["days"] if _conf else None)
    for e in _cal["extras"][:3]:
        _evt_row(e["name"], e.get("hint", ""), e["date"], e["days"])

    st.caption("橘色＝10 天內　·　法說會依公司公告，未公告顯示『未公布』；營收/財報為法定截止推算")

tab_chip, tab_fund, tab_val, tab_tech, tab_news, tab_report, tab_industry, tab_debate, tab_map = st.tabs(
    ["🎯 籌碼面", "📊 基本面", "💰 估值", "📐 技術面", "📰 相關新聞", "📑 投顧動向", "🏭 產業/供應鏈", "🧠 請專家們討論", "🗺️ 市場地圖"]
)

# --- 🧠 請專家們討論 --------------------------------------------------------
with tab_debate:
    st.markdown("#### 🧠 請專家們討論")
    st.caption("輸入代號/中文名，專家即時抓『最新數據＋個股新聞＋投顧動向＋🌍國際資金面＋你的知識庫』，互相點名辯論、交鋒兩輪後給結論與進場時機。")
    dc1, dc2, dc3 = st.columns([2, 1, 1])
    dq = dc1.text_input("股票代號或中文名稱（如 2330 或 台積電）", value=sid, key="debate_q").strip()

    # 「去讀投顧報告」按鈕
    if dc3.button("📄 去讀投顧報告", width="stretch"):
        with st.spinner("掃描待閱讀區..."):
            report_result = read_reports.read_pending_reports()
            st.success(report_result)

    # 「請專家們討論」按鈕
    run_debate_btn = dc2.button("🚀 請專家們討論", width="stretch")

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
        _flow_metric(a, f"外資淨買賣（近{chips.get('window_days','?')}日）",
                     chips.get("foreign_net_20d_lots"), help_=HELP["foreign_net"])
        _flow_metric(b, "投信淨買賣（同期）",
                     chips.get("trust_net_20d_lots"), help_=HELP["trust_net"])
        _metric(c, "外資持股比例", chips.get("foreign_holding_pct"), "%", help_=HELP["foreign_hold"])
        _metric(d, "融資餘額", f"{chips.get('margin_balance_lots'):,}" if chips.get("margin_balance_lots") is not None else None, " 張",
                help_=HELP["margin"] + f"（近45日變化 {chips.get('margin_change_lots')} 張）")

        # 大戶持股 / 籌碼集中度（集保股權分散）
        if chips.get("big_holder_pct") is not None:
            st.markdown("##### 🧱 籌碼集中度（集保大戶持股）")
            e, f2, g = st.columns(3)
            trend = chips.get("big_holder_trend")
            _metric(e, "大戶持股比（>400張）", chips.get("big_holder_pct"), "%",
                    help_="集保股權分散表中，持股 400 張以上者佔總股數比例。越高代表籌碼越集中在大戶手裡（較穩定）。")
            e.caption(f"近16週趨勢 {trend:+}%（正=籌碼往大戶沉澱）" if trend is not None else "")
            _metric(f2, "超級大戶（>1000張）", chips.get("super_holder_pct"), "%",
                    help_="持股 1000 張以上者佔比，徐黎芳所稱『千張大戶』。")
            g.metric("資料週", chips.get("holding_date", "—"))
        elif chips.get("concentration_error"):
            st.caption(f"🧱 籌碼集中度讀取問題：{chips['concentration_error']}（可能需 FinMind token，跑 scripts/probe_holding.py 診斷）")
        st.divider()
        inst = _inst(sid)
        if not inst.empty:
            inst = inst.copy()
            inst["淨買賣（張）"] = (inst["buy"] - inst["sell"]) / 1000.0
            name_map = {"Foreign_Investor": "外資", "Investment_Trust": "投信",
                        "Dealer_self": "自營商（自行買賣）", "Dealer_Hedging": "自營商（避險）",
                        "Foreign_Dealer_Self": "外資自營"}
            inst["法人"] = inst["name"].map(name_map).fillna(inst["name"])
            keep = inst[inst["法人"].isin(["外資", "投信"])].copy()
            # 每日淨買賣 bar：只看外資（日內主力），買超紅、賣超綠，乾淨無花紋
            fdf = keep[keep["法人"] == "外資"].copy()
            fdf["方向"] = fdf["淨買賣（張）"].apply(
                lambda v: "買超" if v > 0 else ("賣超" if v < 0 else "持平"))
            fig = px.bar(fdf, x="date", y="淨買賣（張）", color="方向",
                         color_discrete_map=BUYSELL_COLORS,
                         category_orders={"方向": ["買超", "賣超", "持平"]},
                         title="外資每日買賣超（紅＝買超 / 綠＝賣超）")
            fig.update_layout(xaxis_title="日期")
            st.plotly_chart(fig, width="stretch")

            # 累積淨買賣 線圖（看趨勢方向）
            keep_sorted = keep.sort_values("date").copy()
            keep_sorted["累積淨買賣（張）"] = keep_sorted.groupby("法人")["淨買賣（張）"].cumsum()
            figc = px.line(keep_sorted, x="date", y="累積淨買賣（張）", color="法人",
                           markers=True,
                           color_discrete_map={"外資": UP_RED, "投信": "#1f77b4"},
                           title="三大法人累積淨買賣趨勢（線往上＝持續買超）")
            figc.add_hline(y=0, line_dash="dot", line_color=NEUTRAL_GRAY)
            figc.update_layout(xaxis_title="日期")
            st.plotly_chart(figc, width="stretch")

        # 融資融券餘額 線圖
        ms = _margin_short(sid)
        if ms is not None and not ms.empty:
            st.divider()
            st.markdown("#### 💳 融資融券餘額趨勢",
                        help="融資餘額升＝散戶借錢做多增加（過高常是潛在賣壓）；融券餘額升＝放空力道增加。")
            figm = go.Figure()
            figm.add_trace(go.Scatter(
                x=ms["date"], y=ms["融資餘額"], name="融資餘額（左軸）",
                mode="lines+markers", line=dict(color=UP_RED, width=2),
                hovertemplate="融資 %{y:,.0f} 張<extra></extra>"))
            figm.add_trace(go.Scatter(
                x=ms["date"], y=ms["融券餘額"], name="融券餘額（右軸）",
                mode="lines+markers", line=dict(color=DOWN_GREEN, width=2), yaxis="y2",
                hovertemplate="融券 %{y:,.0f} 張<extra></extra>"))
            figm.update_layout(
                title="融資（紅，左軸）vs 融券（綠，右軸）餘額（張）",
                xaxis_title="日期",
                yaxis=dict(title="融資餘額（張）"),
                yaxis2=dict(title="融券餘額（張）", overlaying="y", side="right",
                            showgrid=False),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(figm, width="stretch")
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
        with col1:
            st.markdown("**📅 月營收年增率 YoY（%）**")
            if rev:
                rdf = pd.DataFrame(rev).rename(columns={"month": "月份", "yoy_pct": "YoY %"})
                sty = (rdf.style
                       .map(_pos_red_neg_green, subset=["YoY %"])
                       .format({"YoY %": "{:+.1f}"}))
                st.dataframe(sty, hide_index=True, width="stretch")
            else:
                st.caption("無月營收年增率資料。")
        eps = fund.get("eps_recent") or []
        with col2:
            st.markdown("**💰 近四季每股盈餘 EPS（元）**")
            if eps:
                edf = pd.DataFrame(eps).rename(columns={"q": "財報季", "eps": "EPS"})
                sty = (edf.style
                       .map(_pos_red_neg_green, subset=["EPS"])
                       .format({"EPS": "{:.2f}"}))
                st.dataframe(sty, hide_index=True, width="stretch")
            else:
                st.caption("無 EPS 資料。")

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
    # 估值分頁：先給答案再給算式——頂部「估值總覽」把六法目標價放同一把尺直接比較，
    # 各方法的計算明細全部收進 expander（點開才看）。方法依《超前部署賺好股》第4篇。
    _cur_px = price.get("close") if isinstance(price, dict) else None
    _rep = None
    try:
        _rep = vdisp.show_valuation_overview(sid, _cur_px)
    except Exception as _e:
        st.error(f"估值總覽計算發生問題：{_e}")
    st.caption("方法出處《超前部署賺好股》：內在價值法（DCF）＋ 財務比率法（現金報酬率/P/E/PEG/P/CF），"
               "詳見 知識庫/書籍筆記/超前部署賺好股/孫慶龍企業估值方法總整理.md。以下為各方法計算明細（點開展開）。")
    st.divider()

    with st.expander("🔢 孫慶龍 8 步驟法——「預估 EPS」怎麼來（所有比率法的原料）"):
        vdisp.show_sun_forecast(sid)

    with st.expander("🏦 內在價值法：DCF 現金流量折現——買進價/賣出目標（風險貼水可調，總覽即時連動）"):
        try:
            vdisp.show_sun_dcf(sid, _cur_px)
        except Exception as _e:
            st.error(f"DCF 估值計算發生問題：{_e}")

    with st.expander("💰 現金報酬率——財務比率法之首（作者首選）"):
        try:
            vdisp.show_cash_return(sid, _cur_px)
        except Exception as _e:
            st.error(f"現金報酬率計算發生問題：{_e}")

    with st.expander("💎 財務比率法：多維度目標價明細（本益比P/E 雙基準・本益成長比PEG・股價現金流比P/CF・投顧反推）"):
        try:
            vdisp.show_multidim_valuation(sid, _cur_px, rep=_rep)
        except Exception as _e:
            st.error(f"多維度估值計算發生問題：{_e}")

    with st.expander("📦 原有估值指標（本益比PER・股價淨值比PBR・股利・河流圖・分析師目標價）"):
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
                # 由低到高：紅(便宜) -> 綠(貴)（台股慣例：便宜該買=紅、昂貴=綠）
                shades = ["rgba(231,76,60,0.18)", "rgba(230,126,34,0.18)", "rgba(247,202,24,0.18)",
                          "rgba(135,196,64,0.18)", "rgba(38,166,91,0.18)"]
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
                st.caption("※ 只列出新聞標題中**有具名券商/機構**者（瑞銀、大摩、高盛、里昂…），泛稱『外資/法人』與媒體名一律不列。仍建議點原文核對。")
            else:
                st.info("近期新聞中未擷取到明確目標價數字。註：免費資料源沒有結構化的各券商目標價（屬付費資料），"
                        "此功能靠新聞擷取，量取決於新聞多寡——填 FinMind token 後新聞變多會更有料。")
        else:
            st.warning(f"估值資料讀取問題：{val.get('error') if isinstance(val, dict) else val}")

# --- 技術面 ----------------------------------------------------------------
with tab_tech:
    st.markdown("#### 📐 技術面指標")

    # --- 🕯️ K 線圖（日K/周K/月K + 均線 + 量）---
    st.markdown("##### 🕯️ K 線圖")
    _period = st.radio("週期", ["日K", "周K", "月K"], horizontal=True,
                       label_visibility="collapsed", key="kline_period")
    _kdf = _kline(sid, _period)
    if _kdf is None or _kdf.empty:
        st.info("查無 K 線資料（可能 FinMind 額度或代號問題）。")
    else:
        from plotly.subplots import make_subplots
        _RED, _GREEN = "#d62728", "#0a9e6e"  # 台股慣例：漲紅、跌綠
        _xfmt = "%Y/%m" if _period == "月K" else "%Y/%m/%d"
        _x = _kdf["date"].dt.strftime(_xfmt)  # 用字串當類別軸，去掉假日空隙
        _ma_palette = ["#ff9800", "#2196f3", "#9c27b0", "#607d8b"]
        _mas = _MA_BY_PERIOD.get(_period, [5, 10, 20, 60])
        kfig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                             row_heights=[0.76, 0.24])
        kfig.add_trace(go.Candlestick(
            x=_x, open=_kdf["open"], high=_kdf["high"], low=_kdf["low"], close=_kdf["close"],
            name="K線", increasing_line_color=_RED, increasing_fillcolor=_RED,
            decreasing_line_color=_GREEN, decreasing_fillcolor=_GREEN), row=1, col=1)
        for _i, _n in enumerate(_mas):
            kfig.add_trace(go.Scatter(x=_x, y=_kdf[f"MA{_n}"], name=f"MA{_n}", mode="lines",
                                      line=dict(color=_ma_palette[_i % len(_ma_palette)], width=1)),
                           row=1, col=1)
        _vcol = [_RED if c >= o else _GREEN for o, c in zip(_kdf["open"], _kdf["close"])]
        kfig.add_trace(go.Bar(x=_x, y=_kdf["vol"], marker_color=_vcol, name="量",
                              showlegend=False), row=2, col=1)
        kfig.update_layout(height=540, hovermode="x unified", xaxis_rangeslider_visible=False,
                           legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
                           margin=dict(t=28, b=8))
        kfig.update_xaxes(type="category", nticks=12, row=2, col=1)
        kfig.update_yaxes(title_text="價(元)", row=1, col=1)
        kfig.update_yaxes(title_text="量(張)", row=2, col=1)
        st.plotly_chart(kfig, width="stretch")
        _ma_label = "、".join(f"MA{n}" for n in _mas)
        st.caption(f"均線（依顏色順序 橘/藍/紫/灰）：{_ma_label}　·　台股慣例：漲紅跌綠")
    st.divider()

    st.caption("ATR（Average True Range，平均真實波幅）衡量近 14 個交易日的市場波動度，用於科學設置止損點位。計算方法與 TradingView 一致（Wilder's RMA）。")

    atr_data = _atr(sid)
    if atr_data.get("error"):
        st.error(f"ATR 計算失敗：{atr_data['error']}")
    else:
        atr_val = atr_data["atr"]
        close_val = atr_data["close"]

        # --- 核心數值 ---
        st.markdown("##### 📏 ATR 止損參考（14日 Wilder's RMA）")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "ATR（14日）",
            f"{atr_val} 元",
            help="近 14 個交易日真實波幅的 Wilder 平滑平均值。代表市場『正常波動』的範圍，止損不應設在這個範圍內，否則容易被正常震盪洗出場。",
        )
        c2.metric(
            "止損帶 1× ATR",
            f"{atr_data['stop_1x']} 元",
            help=f"收盤 {close_val} − 1×ATR {atr_val} = {atr_data['stop_1x']}　｜　適合波動小、趨勢明確時使用，止損較緊。",
        )
        c3.metric(
            "止損帶 1.5× ATR",
            f"{atr_data['stop_15x']} 元",
            help=f"收盤 {close_val} − 1.5×ATR = {atr_data['stop_15x']}　｜　最常用的倍數，兼顧空間與風險控制。",
        )
        c4.metric(
            "止損帶 2× ATR",
            f"{atr_data['stop_2x']} 元",
            help=f"收盤 {close_val} − 2×ATR = {atr_data['stop_2x']}　｜　波動大、行情不確定時給更多生存空間。",
        )
        st.caption(
            f"資料日：{atr_data['date']}　｜　收盤：{close_val} 元　｜　"
            "⚠️ 止損點僅供計算參考，請配合支撐位/壓力位綜合判斷。"
        )

        st.info(
            f"📖 **使用方法**：若你在 **{close_val}** 元附近進場做多，"
            f"可將止損設在支撐位之下約 **1~2 倍 ATR**（{atr_data['stop_1x']}～{atr_data['stop_2x']} 元），"
            f"讓價格有足夠空間應對正常波動，避免被無效洗盤掃出場。"
        )

        # --- ATR 歷史趨勢線 ---
        series = atr_data.get("series", [])
        if len(series) >= 5:
            st.divider()
            st.markdown("##### 📈 ATR 近30日趨勢（波動度變化）")
            sdf = pd.DataFrame(series)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=sdf["date"], y=sdf["atr"],
                mode="lines+markers",
                line=dict(color="#f39c12", width=2),
                fill="tozeroy",
                fillcolor="rgba(243,156,18,0.12)",
                hovertemplate="ATR: %{y:.2f} 元<extra></extra>",
            ))
            fig.update_layout(
                xaxis_title="日期",
                yaxis_title="ATR（元）",
                hovermode="x unified",
                height=280,
            )
            st.plotly_chart(fig, width="stretch")
            st.caption("ATR 值上升＝市場波動加劇（可能在大行情中），下降＝盤整或波動縮小。")

    st.divider()
    st.caption("📌 Phase 3 SOP 評分紅綠燈（技術面部分）將在此分頁擴充，目前先展示 ATR 止損工具。")


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
    # 最上方：具名券商目標價彙整（券商名稱 / 目標價 / 日期）
    st.markdown("#### 🎯 券商目標價彙整")
    _ref_tp = price.get("close") if isinstance(price, dict) else None
    _tp_news_df = _tp_news(sid)
    _tps = (_extract_target_prices(_tp_news_df, _ref_tp)
            if _tp_news_df is not None and not _tp_news_df.empty else [])
    if _tps:
        for t in _tps:
            st.markdown(
                f"- **{t['來源/券商']}**　目標價 **{t['目標價']}**　"
                f"<span style='color:#888'>（{str(t['date'])[:10]}）</span>",
                unsafe_allow_html=True,
            )
        st.caption("※ 僅列新聞標題中**具名券商/機構**者（瑞銀、大摩、高盛、里昂…），泛稱「外資/法人」與媒體名不列。")
    else:
        st.info("近期新聞未擷取到具名券商的目標價。")

    st.divider()
    # 下方：只列「與關鍵數據相關」的新聞/網址（含數字＋投資關鍵字），避免雜訊
    st.markdown("##### 🔑 關鍵數據相關新聞")
    news = _news(sid)
    if news is not None and not news.empty:
        def _is_key(t):
            t = str(t)
            return any(k in t for k in _KEY_DATA_TERMS) and bool(re.search(r"\d", t))
        hits = news[news["title"].apply(_is_key)].head(15)
        if not hits.empty:
            for _, r in hits.iterrows():
                d = str(r["date"])[:10]
                st.markdown(
                    f"- `{d}` [{r['title']}]({r['link']})　"
                    f"<span style='color:#aaa;font-size:0.78em'>{r['source']}</span>",
                    unsafe_allow_html=True,
                )
            st.caption("※ 僅列標題含『目標價/評等/EPS/營收/毛利…』等關鍵字且帶數字者，點連結看原文。")
        else:
            st.info("近期沒有含關鍵數據（目標價/評等/EPS…）的投顧或法人新聞。")
    else:
        st.info("近期查無新聞。")

# --- 產業 / 供應鏈 ---------------------------------------------------------
with tab_industry:
    try:
        info = fm.stock_info(sid)
    except Exception:
        info = None
    cats = (sorted(set(info["industry_category"].dropna()))
            if info is not None and not info.empty else [])
    st.markdown(f"**產業分類：** {('、'.join(cats)) if cats else '—'}")

    # 🏢 這間公司在做什麼（Gemini 自動生成，快取一天）
    if gem.is_configured():
        prof = _company_profile(sid)
        if prof:
            st.markdown("#### 🏢 這間公司在做什麼")
            st.info(prof)
            st.caption("※ 由 AI 依公開資訊生成，數字/占比請再核對，僅供建立公司輪廓。")
    else:
        st.caption("🏢 想看『這間公司在做什麼』的白話簡介？在 `.env` 填 `GEMINI_KEY` 並重啟即可自動生成。")

    st.divider()
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

# ---------------------------------------------------------------------------
# 🗺️  市場地圖
# ---------------------------------------------------------------------------
_MAP_UP_RED     = "#d62728"
_MAP_DOWN_GREEN = "#1ca35a"
_MAP_NEUTRAL    = "#808495"

_WEIGHT_BADGE = {
    "core": ("<span style='background:#d62728;color:#fff;padding:1px 7px;border-radius:10px;"
             "font-size:0.75em;font-weight:600'>核心受惠</span>"),
    "mid":  ("<span style='background:#e07b39;color:#fff;padding:1px 7px;border-radius:10px;"
             "font-size:0.75em;font-weight:600'>間接受惠</span>"),
    "side": ("<span style='background:#555;color:#ddd;padding:1px 7px;border-radius:10px;"
             "font-size:0.75em;font-weight:600'>題材相關</span>"),
}


def _pct_color(pct: float) -> str:
    if pct >= 0.3:
        return _MAP_UP_RED
    if pct <= -0.3:
        return _MAP_DOWN_GREEN
    return _MAP_NEUTRAL


def _pct_badge(pct: float, has_data: bool) -> str:
    if not has_data:
        return "<span style='color:#888'>–</span>"
    color = _pct_color(pct)
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    return f"<span style='color:{color};font-weight:600'>{arrow} {pct:+.2f}%</span>"


with tab_map:
    # 把市場地圖裡的 st.button 樣式改成乾淨的 chip
    st.markdown("""
    <style>
    [data-testid="stHorizontalBlock"] button[kind="secondary"] p { font-size:0.82em; }
    div[data-testid="column"]:has(button[data-testid^="map_jump"]) button {
        background:transparent !important;
        border:1px solid #444 !important;
        border-radius:6px !important;
        padding:2px 8px !important;
        font-size:0.82em !important;
        color:#ccc !important;
        font-family:monospace !important;
        min-height:0 !important;
        height:auto !important;
    }
    </style>""", unsafe_allow_html=True)

    with st.spinner("載入報價中…"):
        try:
            theme_map, changes = td.get_theme_changes()
        except Exception as _e:  # noqa: BLE001
            st.error(f"市場地圖載入失敗：{_e}")
            theme_map, changes = {}, {}

    if not theme_map:
        st.stop()

    _has_data = any(v != 0.0 for v in changes.values())

    st.markdown("#### 🗺️ 市場地圖")

    st.divider()

    # ── 產業鏈切換 ──
    _chain_names = [f"{c.get('emoji','')} {c['name']}" for c in theme_map["chains"]]
    _sel_chain = st.radio("選擇產業鏈", _chain_names, horizontal=True, key="map_chain_radio")
    _chain_idx = _chain_names.index(_sel_chain)
    _cur_chain = theme_map["chains"][_chain_idx]

    st.markdown(
        f"<p style='color:#aaa;font-size:0.85em;margin-top:4px'>"
        f"圖例：{_WEIGHT_BADGE['core']} &nbsp; {_WEIGHT_BADGE['mid']} &nbsp; {_WEIGHT_BADGE['side']}"
        f"　　點股票代號可跳到個股研究</p>",
        unsafe_allow_html=True,
    )

    # ── 各 Stage 卡片 ──
    for stage in _cur_chain.get("stages", []):
        stocks = stage.get("stocks", [])
        _spcts = [changes.get(s["sid"], 0.0) for s in stocks]
        _savg  = sum(_spcts) / len(_spcts) if _spcts else 0.0
        _sh_color = _MAP_UP_RED if _savg > 0 and _has_data else (_MAP_DOWN_GREEN if _savg < 0 and _has_data else _cur_chain.get("color","#555"))

        # 卡片標頭
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin:18px 0 6px 0'>"
            f"<span style='background:{_sh_color};color:#fff;padding:3px 10px;"
            f"border-radius:6px;font-size:0.82em;font-weight:700;white-space:nowrap'>"
            f"{stage['step']}</span>"
            f"<span style='font-size:1.05em;font-weight:700'>{stage['name']}</span>"
            f"<span style='margin-left:auto;color:#888;font-size:0.85em'>{len(stocks)} 檔</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # 表格標頭
        _hc = st.columns([1, 1.8, 5])
        _hc[0].markdown("**代號**")
        _hc[1].markdown("**公司**")
        _hc[2].markdown("**具體在做什麼**")
        st.markdown("<hr style='margin:2px 0 4px 0;border-color:#333'>", unsafe_allow_html=True)

        for s in stocks:
            _ssid = s["sid"]
            _rc   = st.columns([1, 1.8, 5])

            # 代號 → 點擊跳轉按鈕
            if _rc[0].button(_ssid, key=f"map_jump_{_cur_chain['id']}_{stage['id']}_{_ssid}",
                              help=f"點擊 → 跳至 {s['name']} 個股研究"):
                st.session_state["_map_pending_sid"] = _ssid
                st.rerun()

            _rc[1].markdown(
                f"{s['name']}<br>{_WEIGHT_BADGE.get(s.get('weight','side'), '')}",
                unsafe_allow_html=True,
            )
            _rc[2].markdown(
                f"<span style='font-size:0.9em;color:#ccc'>{s.get('note','')}</span>",
                unsafe_allow_html=True,
            )

        # ── 🤖 AI 深入分析這個環節 ──
        _stage_key = f"stage_analysis_{_cur_chain['id']}_{stage['id']}"
        if gem.is_configured():
            if st.button(
                f"🤖 深入了解「{stage['name']}」這個環節",
                key=f"btn_stage_{_cur_chain['id']}_{stage['id']}",
            ):
                st.session_state[_stage_key] = None   # 清快取強制重生
                st.rerun()

            _cached = st.session_state.get(_stage_key, "NOT_SET")
            if _cached == "NOT_SET":
                pass   # 尚未按，不顯示
            elif _cached is None:
                # 需要生成
                _stock_lines = "\n".join(
                    f"   - {s['name']}({s['sid']})：{_WEIGHT_BADGE.get(s.get('weight','side'),'').replace('<','').replace('>','').split('>')[-1] if '>' in _WEIGHT_BADGE.get(s.get('weight','side'),'') else s.get('weight','')}，{s.get('note','')}"
                    for s in stocks
                )
                _prompt = f"""你是台灣股市產業分析師，請針對以下產業環節做深度說明，用台灣投資人看得懂的語言。

產業鏈：{_cur_chain['name']}
環節：{stage['step']} {stage['name']}

本環節的個股（含角色）：
{_stock_lines}

請回答以下三個問題，條列清楚，不要廢話：

① 【這個環節在做什麼？】
   - 白話說明這個環節的技術/商業角色（假設讀者完全不懂，需要從頭解釋）
   - 在整條供應鏈的位置：上游是什麼、下游是什麼、為什麼這個環節重要
   - 有什麼技術門檻讓不是每家公司都能做

② 【各家公司的實際地位】
   - 逐一說明上面每家公司在這個環節的真實競爭力
   - 誰是最核心受惠？為什麼？（市佔、客戶結構、技術護城河）
   - 誰是邊緣角色？邊緣在哪裡？

③ 【目前景氣與風險】
   - 這個環節目前的供需狀況
   - 主要催化劑（什麼事情發生會讓這個環節爆發）
   - 主要風險（什麼事情發生會讓這個環節反轉）

繁體中文，每個問題各自分段，用數字或符號條列。"""
                with st.spinner(f"Gemini 分析「{stage['name']}」中…"):
                    try:
                        _result = gem.generate(_prompt, timeout=90)
                        st.session_state[_stage_key] = _result
                        st.rerun()
                    except Exception as _ge:
                        st.error(f"Gemini 生成失敗：{_ge}")
                        st.session_state[_stage_key] = "ERROR"
            elif _cached != "ERROR":
                with st.expander(f"🤖 AI 產業分析：{stage['name']}", expanded=True):
                    st.markdown(_cached)
                    st.caption("※ 由 Gemini 依公開知識生成，數字請再核對，快取 24h。")
        else:
            st.caption("🤖 想看這個環節的 AI 深度分析？在 `.env` 填 `GEMINI_KEY` 並重啟即可。")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    st.divider()
    st.caption(
        "💡 想新增/修改個股或產業鏈？開啟 "
        r"`G:\我的雲端硬碟\stockbrain\工具欄\theme_map.json`"
        " 直接編輯，重新整理頁面即生效（30分鐘自動更新報價）。"
    )
