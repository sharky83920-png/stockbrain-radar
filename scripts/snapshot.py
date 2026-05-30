"""列印個股研究快照。用法: python scripts/snapshot.py 2330"""
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.snapshot import build_snapshot


def main() -> None:
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    snap = build_snapshot(sid)
    print(json.dumps(snap, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
