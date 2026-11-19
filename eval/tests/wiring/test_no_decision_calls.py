"""FR-002.11: no harness module contains a call whose literal path ends in a decision segment.
The scan carries its own planted-call self-test (its control)."""

from __future__ import annotations

import ast
from pathlib import Path

import miassist_eval

PKG = Path(miassist_eval.__file__).resolve().parent
ENDINGS = ("/approve", "/deny", "/reject", "/approve-batch")
#: The block list itself names the routes it REFUSES; those literals are data, not calls.
DATA_MODULES = frozenset({"edge.py"})


def _strings(node: ast.AST) -> list[str]:
    """String literals in an argument; an f-string counts once, by its literal tail."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        tail = node.values[-1] if node.values else None
        return [str(tail.value)] if isinstance(tail, ast.Constant) else []
    out: list[str] = []
    for child in ast.iter_child_nodes(node):
        out += _strings(child)
    return out


def decision_calls(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            found += [s for s in _strings(arg) if s.rstrip("/").endswith(ENDINGS)]
    return found


def test_the_scan_finds_a_planted_call() -> None:
    planted = (
        "async def f(client, aid):\n"
        "    await client.post(f'/api/v1/approvals/{aid}/approve')\n"
        "    client.request('POST', '/api/approvals/approve-batch')\n"
    )
    assert len(decision_calls(planted)) == 2


def test_no_harness_module_calls_a_decision_route() -> None:
    files = [p for p in PKG.rglob("*.py") if p.name not in DATA_MODULES]
    assert len(files) > 20, "the scan saw too few modules"
    found = {str(p.relative_to(PKG)): decision_calls(p.read_text()) for p in files}
    assert {k: v for k, v in found.items() if v} == {}


def test_edge_holds_the_routes_only_in_its_block_list() -> None:
    """edge.py is exempt from the call scan because DECISION_ROUTES is a frozenset(...) call; every
    decision-shaped literal in it must sit inside that one assignment."""
    tree = ast.parse((PKG / "edge.py").read_text())
    block = next(
        n
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign))
        and getattr(n, "target", None) is not None
        and getattr(n.target, "id", "") == "DECISION_ROUTES"
    )
    inside = {id(c) for c in ast.walk(block)}
    stray = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.rstrip("/").endswith(ENDINGS)
        and id(n) not in inside
    ]
    assert stray == []
