"""FinMind API 薄封裝。

FinMind 是免費的台股資料 API，文件：https://finmind.github.io/
無 token 也能用（低速率），註冊免費 token 後額度大幅提高。
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import requests

from . import cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 還沒裝也不致命
    pass

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


class FinMindError(RuntimeError):
    pass


def _token() -> str:
    return os.environ.get("FINMIND_TOKEN", "")


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
    cache_key = f"{dataset}|{data_id}|{start_date}|{end_date}"
    if use_cache:
        cached = cache.get(cache_key, max_age_days=max_age_days)
        if cached is not None:
            return pd.DataFrame(cached)

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

    resp = requests.get(FINMIND_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        raise FinMindError(f"FinMind 回傳錯誤: {payload.get('status')} {payload.get('msg')}")
    records = payload.get("data", [])
    if use_cache:
        cache.put(cache_key, records)
    return pd.DataFrame(records)


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
