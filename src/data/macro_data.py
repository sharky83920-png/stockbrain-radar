"""國際情勢硬數據：即時市場行情(yfinance) + 美國官方總經(FRED)。

設計：補「新聞標題天生落後」的盲點，給國際情勢專家權威即時數值。
- 市場行情：免金鑰(yfinance)。台幣匯率／費半／VIX／美10年期殖利率／那斯達克。
- 美國總經：需 FRED_KEY（免費申請 https://fredaccount.stlouisfed.org/apikeys）。
            CPI 年增率／聯邦基金利率／10年期公債殖利率。
全部 best-effort：抓不到就略過，不讓討論中斷。
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta

import requests

from . import finmind_client as fm

# 同一輪排程會對很多檔重複呼叫；用 30 分鐘記憶體快取，一輪只真正抓一次。
_CACHE: dict[str, tuple[float, object]] = {}
_TTL = 1800


def _cached(key: str, fn):
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val

# (代號, 顯示名, 給 AI 的解讀提示)　全球總經/資金面
_MARKET = [
    ("DX-Y.NYB", "美元指數DXY", "升=資金回流美國、新興市場失血"),
    ("TWD=X", "美元/台幣", "升=台幣貶=外資可能撤"),
    ("^GSPC", "標普500", "美股大盤全貌"),
    ("^IXIC", "那斯達克", "美科技股風向"),
    ("^DJI", "道瓊", "美傳產/大型股"),
    ("^SOX", "費城半導體", "台積電/半導體連動"),
    ("^VIX", "VIX恐慌指數", ">20偏恐慌、避險升溫"),
    ("^TNX", "美10年期殖利率%", "走高壓抑高估值成長股"),
    ("^IRX", "美3月期殖利率%", "短率；配10年看殖利率曲線"),
    ("GC=F", "黃金", "避險/抗通膨"),
    ("CL=F", "西德州原油", "通膨與景氣動能"),
    ("BTC-USD", "比特幣", "風險胃納溫度計"),
    ("^N225", "日經225", "亞股連動"),
    ("000001.SS", "上證指數", "中國市場"),
    ("^HSI", "恆生指數", "港股/中國資金"),
]
# 半導體國際連動（牽動台積電供應鏈）
_SEMI = [
    ("NVDA", "輝達NVDA", "AI晶片龍頭，台積電最大客戶之一"),
    ("AMD", "超微AMD", "AI/CPU"),
    ("TSM", "台積電ADR", "美股對台積電的定價"),
]


def _quotes(items: list[tuple]) -> list[dict]:
    """通用 yfinance 報價。取『最後一個有效收盤』，避免今天未開盤的 NaN。"""
    try:
        import yfinance as yf
    except Exception:
        return []
    out: list[dict] = []
    for sym, label, note in items:
        try:
            h = yf.Ticker(sym).history(period="7d")
            closes = h["Close"].dropna() if not h.empty else None
            if closes is None or closes.empty:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else last
            chg = (last / prev - 1) * 100 if prev else 0.0
            out.append({"label": label, "value": round(last, 2), "chg_pct": round(chg, 2),
                        "date": str(closes.index[-1].date()), "note": note})
        except Exception:
            continue
    return out


def market_quotes() -> list[dict]:
    return _cached("market", lambda: _quotes(_MARKET))


def semi_quotes() -> list[dict]:
    return _cached("semi", lambda: _quotes(_SEMI))


def yield_curve(mkt: list[dict]) -> str:
    """從已抓的行情算 10年-3月 殖利率曲線。回描述字串或空。"""
    y10 = next((q["value"] for q in mkt if "10年" in q["label"]), None)
    y3m = next((q["value"] for q in mkt if "3月" in q["label"]), None)
    if y10 is None or y3m is None:
        return ""
    spread = round(y10 - y3m, 2)
    tag = "倒掛⚠️(衰退警訊)" if spread < 0 else "正常"
    return f"殖利率曲線(10年-3月)：{spread:+}%（{tag}）"


# (FRED series_id, 顯示名, units 轉換)　units=pc1 → 與去年同月相比的年增率(%)
_FRED = [
    ("CPIAUCSL", "美國CPI年增率(%)", "pc1"),
    ("DFF", "美國聯邦基金利率(%)", None),
    ("DGS10", "美國10年期公債殖利率(%)", None),
]


def us_macro() -> list[dict]:
    return _cached("fred", _us_macro_impl)


def _us_macro_impl() -> list[dict]:
    """FRED 美國官方總經（需 FRED_KEY）。回 [{label,value,date}]，沒 key 或抓不到回 []。"""
    key = os.environ.get("FRED_KEY")
    if not key:
        return []
    out: list[dict] = []
    for sid, label, units in _FRED:
        try:
            params = {"series_id": sid, "api_key": key, "file_type": "json",
                      "sort_order": "desc", "limit": 1}
            if units:
                params["units"] = units
            r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                             params=params, timeout=20)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            if not obs:
                continue
            v = obs[0].get("value")
            if v in (None, ".", ""):
                continue
            out.append({"label": label, "value": round(float(v), 2), "date": obs[0].get("date", "")})
        except Exception:
            continue
    return out


# --- 台股大盤結構：台指期結算日 / 外資期貨淨部位 / 大盤融資水位 -----------------
def _third_wednesday(y: int, m: int) -> date:
    d = date(y, m, 1)
    offset = (2 - d.weekday()) % 7  # 週三=2
    return d + timedelta(days=offset + 14)


def _next_settlement(today: date) -> date:
    """台指期每月結算日＝第三個週三。回下一個（含今天）。"""
    s = _third_wednesday(today.year, today.month)
    if s < today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        s = _third_wednesday(y, m)
    return s


def taiwan_structure() -> list[dict]:
    return _cached("tw_struct", _taiwan_structure_impl)


def _taiwan_structure_impl() -> list[dict]:
    """台股大盤級觀察指標。回 [{label,value}]，抓不到的略過。"""
    out: list[dict] = []
    today = date.today()
    try:
        s = _next_settlement(today)
        days = (s - today).days
        warn = "（本週結算！慎防結算行情/壓盤）" if days <= 4 else ""
        out.append({"label": "台指期結算日", "value": f"{s.isoformat()} ・還有 {days} 天{warn}"})
    except Exception:
        pass
    start = (today - timedelta(days=15)).isoformat()
    try:  # 外資台指期未平倉淨部位（多單-空單）
        df = fm.fetch("TaiwanFutOptInstitutionalInvestors", "TX", start)
        f = df[df["institutional_investors"] == "外資"]
        if not f.empty:
            r = f.sort_values("date").iloc[-1]
            net = int(r["long_open_interest_balance_volume"]) - int(r["short_open_interest_balance_volume"])
            side = "淨多單" if net >= 0 else "淨空單"
            hint = "外資押大盤下跌、偏空" if net < 0 else "偏多"
            out.append({"label": "外資台指期未平倉", "value": f"{side} {abs(net):,} 口 ・{hint}（{r['date']}）"})
    except Exception:
        pass
    try:  # 大盤融資餘額（金額，散戶槓桿水位）+ 融券餘額（張，空方力道）
        df = fm.fetch("TaiwanStockTotalMarginPurchaseShortSale", None, start)
        m = df[df["name"] == "MarginPurchaseMoney"]
        if not m.empty:
            r = m.sort_values("date").iloc[-1]
            bal = float(r["TodayBalance"]) / 1e8
            chg = (float(r["TodayBalance"]) - float(r["YesBalance"])) / 1e8
            trend = "增・散戶加槓桿" if chg > 0 else "減・散戶去槓桿"
            out.append({"label": "大盤融資餘額", "value": f"{bal:,.0f} 億元（日變化 {chg:+,.0f} 億・{trend}）（{r['date']}）"})
        s = df[df["name"] == "ShortSale"]
        if not s.empty:
            r = s.sort_values("date").iloc[-1]
            bal = float(r["TodayBalance"])
            chg = float(r["TodayBalance"]) - float(r["YesBalance"])
            trend = "增・空方轉強" if chg > 0 else "減・空方回補"
            out.append({"label": "大盤融券餘額", "value": f"{bal:,.0f} 張（日變化 {chg:+,.0f} 張・{trend}）（{r['date']}）"})
    except Exception:
        pass
    return out


# --- 重要事件行事曆（前瞻提醒）------------------------------------------------
def cpi_next_release() -> str | None:
    """FRED 抓美國 CPI 下次公布日（release_id=10）。"""
    key = os.environ.get("FRED_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://api.stlouisfed.org/fred/release/dates",
                         params={"release_id": 10, "api_key": key, "file_type": "json",
                                 "sort_order": "desc", "limit": 24,
                                 "include_release_dates_with_no_data": "true"}, timeout=20)
        today = date.today().isoformat()
        future = [rd["date"] for rd in r.json().get("release_dates", []) if rd.get("date", "") >= today]
        return min(future) if future else None
    except Exception:
        return None


def nvda_earnings() -> str | None:
    """yfinance 抓輝達下次財報日。"""
    try:
        import yfinance as yf
        cal = yf.Ticker("NVDA").calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if isinstance(ed, list) and ed:
            return str(ed[0])
        if ed:
            return str(ed)
    except Exception:
        return None
    return None


def calendar_events() -> list[str]:
    return _cached("calendar", _calendar_events_impl)


def _calendar_events_impl() -> list[str]:
    out: list[str] = []
    today = date.today()
    s = _next_settlement(today)
    out.append(f"台指期結算日：{s.isoformat()}（{(s - today).days} 天後）")
    cpi = cpi_next_release()
    if cpi:
        out.append(f"美國CPI下次公布：{cpi}")
    nv = nvda_earnings()
    if nv:
        out.append(f"輝達下次財報：{nv}")
    return out


def summary_lines() -> str:
    return _cached("summary", _summary_lines_impl)


def _summary_lines_impl() -> str:
    """組成硬數據摘要文字（給 prompt 與示範模式共用）。全抓不到回空字串。"""
    lines: list[str] = []
    mq = market_quotes()
    if mq:
        lines.append("【全球市場 yfinance】")
        for q in mq:
            lines.append(f"- {q['label']}：{q['value']}（{q['chg_pct']:+}%・{q['date']}）{q['note']}")
        yc = yield_curve(mq)
        if yc:
            lines.append(f"- {yc}")
    sq = semi_quotes()
    if sq:
        lines.append("【半導體國際連動 yfinance】")
        for q in sq:
            lines.append(f"- {q['label']}：{q['value']}（{q['chg_pct']:+}%・{q['date']}）{q['note']}")
    um = us_macro()
    if um:
        lines.append("【美國官方總經 FRED】")
        for q in um:
            lines.append(f"- {q['label']}：{q['value']}（{q['date']}）")
    ts = taiwan_structure()
    if ts:
        lines.append("【台股大盤結構 FinMind】")
        for q in ts:
            lines.append(f"- {q['label']}：{q['value']}")
    ev = calendar_events()
    if ev:
        lines.append("【重要事件行事曆】")
        for e in ev:
            lines.append(f"- {e}")
    return "\n".join(lines)


def headline() -> str:
    """大環境一行摘要（給推播開頭）。抓不到回空字串。"""
    bits: list[str] = []
    risk_off = 0
    for q in market_quotes():
        if "VIX" in q["label"]:
            bits.append(f"VIX {q['value']}")
            if isinstance(q["value"], (int, float)) and q["value"] > 20:
                risk_off += 1
        if "費城" in q["label"] and isinstance(q.get("chg_pct"), (int, float)) and q["chg_pct"] < -1:
            risk_off += 1
        if "台幣" in q["label"] and isinstance(q.get("chg_pct"), (int, float)) and q["chg_pct"] > 0:
            risk_off += 1
    for q in taiwan_structure():
        if "外資台指" in q["label"]:
            bits.append(q["value"].split("・")[0].replace("未平倉", "").strip() if "・" in q["value"] else q["value"][:14])
            if "淨空" in q["value"]:
                risk_off += 1
    tone = "逆風" if risk_off >= 2 else ("偏逆風" if risk_off == 1 else "中性偏穩")
    return f"🌍 大環境：{tone}" + ("（" + " ・".join(bits) + "）" if bits else "")
