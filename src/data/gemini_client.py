"""Gemini 摘要封裝（REST，沿用使用者 GAS 晨報的 Gemini）。

需在 .env 設定 GEMINI_KEY（與 GAS Script Properties 同一把）。
模型預設 gemini-3.1-flash-lite，可用 GEMINI_MODEL 覆寫。
"""
from __future__ import annotations

import os

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

DEFAULT_MODEL = "gemini-3.1-flash-lite"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_KEY"))


def _model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def generate(prompt: str, timeout: int = 60) -> str:
    key = os.environ.get("GEMINI_KEY")
    if not key:
        raise GeminiNotConfigured("未設定 GEMINI_KEY（請在 .env 填入，與 GAS 晨報同一把）")
    url = ENDPOINT.format(model=_model())
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, params={"key": key}, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini 回應格式非預期：{data}") from e


def summarize_news(titles: list[str], stock_id: str) -> str:
    """把一批新聞標題摘要成 3-5 點重點（繁中）。"""
    joined = "\n".join(f"- {t}" for t in titles[:40])
    prompt = (
        f"你是台股研究助理。以下是個股 {stock_id} 近期的新聞標題，"
        f"請用繁體中文整理成 3-5 點「投資人該知道的重點」，"
        f"聚焦法人動向、目標價/評等、營運與產業變化，避免廢話：\n\n{joined}"
    )
    return generate(prompt)
