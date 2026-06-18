#!/usr/bin/env python
"""Complete integration test of the report processing system"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.report_monitor import manual_scan

if __name__ == "__main__":
    print("Testing report processing system...")
    print("="*60)

    result = manual_scan()

    print("\n" + "="*60)
    print("RESULT:")
    print("="*60)
    print(result)

    # Check generated files
    kb_path = Path("G:/我的雲端硬碟/stockbrain/知識庫/個股")
    if kb_path.exists():
        print("\n" + "="*60)
        print("Generated knowledge base files:")
        print("="*60)
        for md_file in kb_path.glob("**/投顧報告/*.md"):
            print(f"✓ {md_file.relative_to(kb_path)}")
