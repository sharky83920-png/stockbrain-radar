"""國際情勢硬數據：即時市場行情(yfinance) + 美國官方總經(FRED)。

設計：補「新聞標題天生落後」的盲點，給國際情勢專家權威即時數值。
- 市場行情：免金鑰(yfinance)。台幣匯率／費半／VIX／美10年期殖利率／那斯達克。
- 美國總經：需 FRED_KEY（免費申請 https://fredaccount.stlouisfed.org/apikeys）。
            CPI 年增率／聯邦基金利率／10年期公債殖利率。
全部 best-effort：抓不到就略過，不讓討論中斷。
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

from . import finmind_client as fm

# (代號, 顯示名, 給 AI 的解讀提示)
_MARKET = [
    ("TWD=X", "美元/台幣", "走高=台幣貶=外資可能撤離台股"),
    ("^SOX", "費城半導體指數", "台積電/半導體連動指標"),
    ("^VIX", "VIX 恐慌指數", ">20 偏恐慌、避險升溫"),
    ("^TNX", "美10年期公債殖利率(%)", "走高壓抑高本益比成長股"),
    ("^IXIC", "那斯達克指數", "美國科技股風向"),
]


def market_quotes() -> list[dict]:
    """yfinance 即時行情。回 [{label,value,chg_pct,date,note}]，抓不到回 []。"""
    try:
        import yfinance as yf
    except Exception:
        return []
    out: list[dict] = []
    for sym, label, note in _MARKET:
        try:
            h = yf.Ticker(sym).history(period="5d")
            if h.empty:
                continue
            last = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2]) if len(h) > 1 else last
            chg = (last / prev - 1) * 100 if prev else 0.0
            out.append({"label": label, "value": round(last, 2), "chg_pct": round(chg, 2),
                        "date": str(h.index[-1].date()), "note": note})
        except Exception:
            continue
    return out


# (FRED series_id, 顯示名, units 轉換)　units=pc1 → 與去年同月相比的年增率(%)
_FRED = [
    ("CPIAUCSL", "美國CPI年增率(%)", "pc1"),
    ("DFF", "美國聯邦基金利率(%)", None),
    ("DGS10", "美國10年期公債殖利率(%)", None),
]


def us_macro() -> list[dict]:
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


def summary_lines() -> str:
    """組成硬數據摘要文字（給 prompt 與示範模式共用）。全抓不到回空字串。"""
    lines: list[str] = []
    mq = market_quotes()
    if mq:
        lines.append("【即時市場行情 yfinance】")
        for q in mq:
            lines.append(f"- {q['label']}：{q['value']}（{q['chg_pct']:+}% ・{q['date']}）{q['note']}")
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
