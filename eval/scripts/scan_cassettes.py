"""Pre-commit hook (FTASKS 4.5): refuse a commit when any cassette holds a secret, raw or base64.

eval/.venv/bin/python eval/scripts/scan_cassettes.py   # exit 1 on any finding
"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL)]

from miassist_eval import secret_scan  # noqa: E402

ROOT = EVAL.parent / "tests" / "fixtures" / "cassettes" / "private"

if __name__ == "__main__":
    hits = secret_scan.scan_tree(ROOT) if ROOT.is_dir() else {}
    for path, found in hits.items():
        print(f"SECRET {path}: {found}")
    sys.exit(1 if hits else 0)
