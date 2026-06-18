#!/usr/bin/env python
"""Check PDF content to improve extraction patterns"""
import pdfplumber
from pathlib import Path

pdf_dir = Path("G:/我的雲端硬碟/stockbrain/待閱讀區")
pdf_files = list(pdf_dir.glob("*.pdf"))

for pdf_path in pdf_files[:1]:
    print(f"Checking: {pdf_path.name}")
    print("="*60)

    with pdfplumber.open(str(pdf_path)) as pdf:
        print(f"Total pages: {len(pdf.pages)}\n")

        for i, page in enumerate(pdf.pages[:2]):
            print(f"--- Page {i+1} ---")
            text = page.extract_text()
            if text:
                # Print first 1500 chars
                print(text[:1500])
                print("\n" + "="*60 + "\n")
