"""miDataworks' behaviour-dataset journey rule, vendored as data for the fakes (R3 review fix
OR3-int-3, 2026-11-16; OVN-miassist-int-28).

The 003 fake built its status by hand (``next.step == "send"`` with no send), a status the real
rule never produces: the fixture agreed with miAssist by construction. The fake now derives
``journey``, ``next`` and ``complete`` from the world's counts with miDataworks' own step table
(``backend/src/services/behaviour/journey.py``: each step done when ``counts[name] >= n``; next is
the first step not done), vendored at ``tests/fixtures/midataworks/journey.json`` and pinned equal
to the sibling's file by ``tests/cross_repo/test_dw_journey_live.py``. Nothing imports miDataworks.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

TABLE = Path(__file__).resolve().parents[1] / "fixtures" / "midataworks" / "journey.json"
SOURCE = "backend/src/services/behaviour/journey.py"


def extract(source: str) -> list[dict[str, Any]]:
    """The ``JOURNEY`` steps of miDataworks' ``journey.py``, read by AST (never executed): key,
    title, tool, done_when, and the ``_at_least(name, n)`` count each step is done at."""
    for node in ast.walk(ast.parse(source)):
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else (node.targets if isinstance(node, ast.Assign) else [])
        )
        if not any(isinstance(t, ast.Name) and t.id == "JOURNEY" for t in targets):
            continue
        assert isinstance(node.value, ast.Tuple), "JOURNEY is not a tuple literal"
        steps = []
        for call in node.value.elts:
            assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Step"
            args = call.args
            done = args[5]
            assert isinstance(done, ast.Call) and getattr(done.func, "id", "") == "_at_least"
            name = ast.literal_eval(done.args[0])
            n = ast.literal_eval(done.args[1]) if len(done.args) > 1 else 1
            steps.append(
                {
                    "step": ast.literal_eval(args[0]),
                    "title": ast.literal_eval(args[1]),
                    "tool": ast.literal_eval(args[2]),
                    "done_when": ast.literal_eval(args[4]),
                    "count": name,
                    "at_least": n,
                }
            )
        return steps
    raise AssertionError("no JOURNEY in miDataworks' journey.py")


@cache
def table() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(TABLE.read_text())["steps"]
    return data


def walk(key: str, counts: Mapping[str, int]) -> dict[str, Any]:
    """``journey.walk`` over the vendored table (the keys the status answer carries)."""
    steps = [
        {
            "step": s["step"],
            "title": s["title"],
            "tool": s["tool"],
            "also": [],
            "approvals": [],
            "done_when": s["done_when"],
            "done": counts.get(s["count"], 0) >= s["at_least"],
        }
        for s in table()
    ]
    nxt = next((s for s in steps if not s["done"]), None)
    return {
        "journey": steps,
        "next": (
            {
                "step": nxt["step"],
                "tool": nxt["tool"],
                "args": {"behaviour_key": key},
                "why": f"Not done yet: {nxt['done_when']}.",
            }
            if nxt
            else None
        ),
        "complete": nxt is None,
    }


def counts_before(step: str | None) -> dict[str, int]:
    """Counts at which ``step`` is the next one (every earlier step done); ``None``: complete."""
    counts: dict[str, int] = {}
    for s in table():
        if s["step"] == step:
            break
        counts[s["count"]] = max(counts.get(s["count"], 0), s["at_least"])
    return counts
