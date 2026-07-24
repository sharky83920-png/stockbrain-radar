"""FinMind API 薄封裝。

FinMind 是免費的台股資料 API，文件：https://finmind.github.io/
無 token 也能用（低速率），註冊免費 token 後額度大幅提高。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from . import cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 還沒裝也不致命
    pass

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 同一資料集常被不同年限重複抓（如財報 300/520/1600/1800/2555 天各抓一次），
# 改成只用下列「標準年限」抓、共用同一份快取，回傳前再裁回呼叫端要的區間。
# 一檔股票每個資料集每天最多打 len(buckets) 次 API，省掉大量重複請求。
_CANON_DAYS: dict[str, list[int]] = {
    "TaiwanStockPrice": [30, 1250],
    "TaiwanStockPER": [30, 1250],
    "TaiwanStockFinancialStatements": [2600],
    "TaiwanStockBalanceSheet": [2600],
    "TaiwanStockMonthRevenue": [1600],
    "TaiwanStockDividend": [3000],
    "TaiwanStockMarginPurchaseShortSale": [90],
    "TaiwanStockInstitutionalInvestorsBuySell": [60],
    "TaiwanStockShareholding": [60],
    "TaiwanStockNews": [30],
}


def _canonical_start(dataset: str, start_date: str) -> str:
    """把要求的起日對齊到該資料集的標準年限（取足以涵蓋的最小桶）。無桶可涵蓋則原樣使用。"""
    buckets = _CANON_DAYS.get(dataset)
    if not buckets:
        return start_date
    try:
        want = (date.today() - date.fromisoformat(start_date)).days
    except ValueError:
        return start_date
    for b in buckets:
        if b >= want:
            return (date.today() - timedelta(days=b)).isoformat()
    return start_date


def _frame(records: list, req_start: str | None, fetched_start: str | None) -> pd.DataFrame:
    """標準年限抓回的資料，裁回呼叫端原本要求的區間。"""
    if req_start and req_start != fetched_start:
        records = [r for r in records if str(r.get("date", "")) >= req_start]
    return pd.DataFrame(records)


class FinMindError(RuntimeError):
    pass


def _token() -> str:
    return os.environ.get("FINMIND_TOKEN", "")


def _expected_latest_trading_day(now: datetime) -> date:
    """現在時點理論上最新可取得的收盤資料日（平日 14:00 後視為當日盤後已發布）。"""
    d = now.date()
    if d.weekday() < 5 and now.hour >= 14:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _price_needs_refresh(records: list, fetched_at: datetime) -> bool:
    """日K快取雖在同日有效期內，但盤後應有新交易日資料時提前重抓。

    每小時最多重抓一次：休市日（颱風假、國定假日）永遠等不到當日資料，
    靠節流避免整個下午重複打 API 燒額度。"""
    now = datetime.now()
    last = max((r.get("date", "") for r in records), default="")
    if last >= _expected_latest_trading_day(now).isoformat():
        return False
    return now - fetched_at >= timedelta(hours=1)


def fetch(
    dataset: str,
    data_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout: int = 30,
    use_cache: bool = True,
    max_age_days: int = 1,
) -> pd.DataFrame:
    """打 FinMind 一個 dataset，回傳 DataFrame。

    Args:
        dataset: FinMind dataset 名，例如 'TaiwanStockPrice'。
        data_id: 股票代號，例如 '2330'。
        start_date / end_date: 'YYYY-MM-DD'。
        use_cache: 是否使用 SQLite 快取（同日重複查直接讀快取）。
    """
    req_start = start_date
    if data_id and start_date and not end_date:
        start_date = _canonical_start(dataset, start_date)

    cache_key = f"{dataset}|{data_id}|{start_date}|{end_date}"
    stale_records: list | None = None
    if use_cache:
        entry = cache.get_entry(cache_key)
        if entry is not None:
            records, fetched_at = entry
            fresh = (date.today() - fetched_at.date()).days <= max_age_days
            if fresh and dataset == "TaiwanStockPrice":
                fresh = not _price_needs_refresh(records, fetched_at)
            if fresh:
                return _frame(records, req_start, start_date)
            stale_records = records

    params: dict[str, str] = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    token = _token()
    if token:
        params["token"] = token

    try:
        resp = requests.get(FINMIND_URL, params=params, timeout=timeout, verify=False)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != 200:
            raise FinMindError(f"FinMind 回傳錯誤: {payload.get('status')} {payload.get('msg')}")
    except Exception as exc:
        # 額度用罄(402)或斷線時，退回舊快取讓頁面能動；完全沒快取才報錯
        if stale_records is not None:
            return _frame(stale_records, req_start, start_date)
        if req_start and req_start != start_date:
            # 標準年限的快取還沒建立過：試試改版前以原始起日存的舊快取
            legacy = cache.get_entry(f"{dataset}|{data_id}|{req_start}|{end_date}")
            if legacy is not None:
                return pd.DataFrame(legacy[0])
        if (
            isinstance(exc, requests.HTTPError)
            and exc.response is not None
            and exc.response.status_code == 402
        ):
            raise FinMindError(
                "FinMind API 額度用罄（402）。無 token 上限 300 次/小時；"
                "至 finmindtrade.com 免費註冊後把 token 填入 .env 的 FINMIND_TOKEN"
                "（600 次/小時），或等額度重置後重新整理。"
            ) from exc
        raise
    records = payload.get("data", [])
    if use_cache:
        cache.put(cache_key, records)
    return _frame(records, req_start, start_date)


# --- 常用資料的便利函式 -------------------------------------------------

def _default_start(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def stock_price(data_id: str, days: int = 120) -> pd.DataFrame:
    """日 K（開高低收量）。"""
    return fetch("TaiwanStockPrice", data_id, _default_start(days))


def institutional_investors(data_id: str, days: int = 60) -> pd.DataFrame:
    """三大法人買賣超（外資/投信/自營）。"""
    return fetch("TaiwanStockInstitutionalInvestorsBuySell", data_id, _default_start(days))


def margin_short(data_id: str, days: int = 60) -> pd.DataFrame:
    """融資融券餘額。"""
    return fetch("TaiwanStockMarginPurchaseShortSale", data_id, _default_start(days))


def month_revenue(data_id: str, days: int = 730) -> pd.DataFrame:
    """月營收。"""
    return fetch("TaiwanStockMonthRevenue", data_id, _default_start(days))


def per_pbr(data_id: str, days: int = 120) -> pd.DataFrame:
    """本益比 / 股價淨值比 / 殖利率。"""
    return fetch("TaiwanStockPER", data_id, _default_start(days))


def financial_statements(data_id: str, days: int = 500) -> pd.DataFrame:
    """綜合損益表（長格式，type 含 EPS / Revenue / GrossProfit / OperatingIncome ...）。"""
    return fetch("TaiwanStockFinancialStatements", data_id, _default_start(days))


def balance_sheet(data_id: str, days: int = 500) -> pd.DataFrame:
    """資產負債表（長格式，type 含 Equity / Liabilities / TotalAssets ...）。"""
    return fetch("TaiwanStockBalanceSheet", data_id, _default_start(days))


def shareholding(data_id: str, days: int = 60) -> pd.DataFrame:
    """外資持股比例（集保 / 投信投顧公會）。"""
    return fetch("TaiwanStockShareholding", data_id, _default_start(days))


def dividend(data_id: str, days: int = 1500) -> pd.DataFrame:
    """歷年股利（現金/股票股利、除息日）。"""
    return fetch("TaiwanStockDividend", data_id, _default_start(days))


def news(data_id: str, days: int = 14) -> pd.DataFrame:
    """個股相關新聞（date / source / title / link）。"""
    return fetch("TaiwanStockNews", data_id, _default_start(days))


def holding_distribution(data_id: str, weeks: int = 16) -> pd.DataFrame:
    """集保股權分散表（持股分級，週資料）。用於大戶持股比 / 籌碼集中度。

    欄位（待驗證）：date / stock_id / HoldingSharesLevel / people / percent / unit。
    """
    return fetch("TaiwanStockHoldingSharesPer", data_id, _default_start(weeks * 7))


def stock_info(data_id: str) -> pd.DataFrame:
    """個股基本資訊（stock_name / industry_category）。"""
    return fetch("TaiwanStockInfo", data_id, max_age_days=30)


def stock_name(data_id: str) -> str | None:
    """回傳股票中文名稱，查不到回 None。"""
    try:
        info = stock_info(data_id)
        if not info.empty:
            return str(info.iloc[0]["stock_name"])
    except Exception:
        pass
    return None


def cash_flow(data_id: str, days: int = 500) -> pd.DataFrame:
    """現金流量表（長格式，type 含 CashFlowsFromOperatingActivities /
    PropertyAndPlantAndEquipment(資本支出) ...）。"""
    return fetch("TaiwanStockCashFlowsStatement", data_id, _default_start(days))


def all_stock_info() -> pd.DataFrame:
    """全市場個股基本資訊（含 industry_category），供同業比較用。快取 30 天。"""
    return fetch("TaiwanStockInfo", max_age_days=30)
