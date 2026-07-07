"""Gemini 摘要封裝（REST，沿用使用者 GAS 晨報的 Gemini）。

需在 .env 設定 GEMINI_KEY（與 GAS Script Properties 同一把）。
模型預設 gemini-3.1-flash-lite，可用 GEMINI_MODEL 覆寫。
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

DEFAULT_MODEL = "gemini-2.5-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_KEY"))


def _model() -> str:
    return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def _post(payload: dict, timeout: int) -> str:
    key = os.environ.get("GEMINI_KEY")
    if not key:
        raise GeminiNotConfigured("未設定 GEMINI_KEY（請在 .env 填入，與 GAS 晨報同一把）")
    url = ENDPOINT.format(model=_model())

    # 金鑰放 header，不放 URL query：避免 HTTPError 訊息把 ?key=... 整串金鑰印出來
    headers = {"x-goog-api-key": key}
    for attempt in range(3):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout, verify=False)
        if resp.status_code in (429, 500, 502, 503, 504):  # 暫時性錯誤都重試（含 503）
            wait = 30 * (attempt + 1)   # 30s / 60s / 90s
            time.sleep(wait)
            continue
        if not resp.ok:  # 帶出 API 回應內文，方便除錯（金鑰在 header 不會外洩）
            raise RuntimeError(f"Gemini HTTP {resp.status_code}：{resp.text[:500]}")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 回應格式非預期：{data}") from e

    raise RuntimeError("Gemini 連續暫時性錯誤(429/5xx)，已重試 3 次仍失敗，請稍後再試")


def generate(prompt: str, timeout: int = 90) -> str:
    return _post({"contents": [{"parts": [{"text": prompt}]}]}, timeout)


# inline_data 整包請求上限 20MB，base64 會膨脹 ~33%，故原始 PDF 限 15MB。
# 更大的（高解析掃描檔，Gemini 對 PDF 文件另有 50MB 硬限制）
# 改成本機把前幾頁渲染成 JPEG 縮圖再 inline 送，任何大小都能處理。
_MAX_INLINE_PDF_MB = 15


def _pdf_pages_as_jpegs(pdf_path: Path, max_pages: int = 8) -> list[bytes]:
    """用 pypdfium2 把前 max_pages 頁渲染成 JPEG（長邊 1600px，OCR 足夠）。"""
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    out = []
    try:
        for i in range(min(len(doc), max_pages)):
            img = doc[i].render(scale=2.0).to_pil()  # 72dpi × 2 = 144dpi
            img.thumbnail((1600, 1600))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=80)
            out.append(buf.getvalue())
    finally:
        doc.close()
    return out


def generate_with_pdf(prompt: str, pdf_path: str | Path,
                      timeout: int = 300, max_pages: int = 8) -> str:
    """帶 PDF 附件呼叫 Gemini（多模態）。掃描檔（無文字層）由模型直接 OCR。

    ≤15MB 整份 inline；更大的改送前 max_pages 頁的 JPEG 縮圖。
    """
    pdf_path = Path(pdf_path)
    data = pdf_path.read_bytes()

    if len(data) <= _MAX_INLINE_PDF_MB * 1024 * 1024:
        parts = [{"inline_data": {
            "mime_type": "application/pdf",
            "data": base64.b64encode(data).decode("ascii"),
        }}]
    else:
        parts = [{"inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(jpg).decode("ascii"),
        }} for jpg in _pdf_pages_as_jpegs(pdf_path, max_pages)]

    parts.append({"text": prompt})
    return _post({"contents": [{"parts": parts}]}, timeout)


def summarize_news(titles: list[str], stock_id: str) -> str:
    """把一批新聞標題摘要成 3-5 點重點（繁中）。"""
    joined = "\n".join(f"- {t}" for t in titles[:40])
    prompt = (
        f"你是台股研究助理。以下是個股 {stock_id} 近期的新聞標題，"
        f"請用繁體中文整理成 3-5 點「投資人該知道的重點」，"
        f"聚焦法人動向、目標價/評等、營運與產業變化，避免廢話：\n\n{joined}"
    )
    return generate(prompt)
