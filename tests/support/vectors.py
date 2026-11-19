"""Whether miWorkbench 045's per-route payload vectors are vendored (001 FTASKS 5.2a; A43, V-4).

A LITERAL, flipped to ``True`` only by push 001-V in the same commit that adds
``docs/schemas/miworkbench-approval-payload-vectors-v1.json``. ``tests/unit/test_vectors_flag.py``
pins the flag to the file's presence. Vector-reading tests skip loudly while it is ``False``; they
never key on the cross-repo require switch.
"""

from __future__ import annotations

from pathlib import Path

VECTORS_VENDORED = True

VECTORS_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "miworkbench-approval-payload-vectors-v1.json"
)
