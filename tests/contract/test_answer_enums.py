"""The answer enums ``src/`` hard-codes match the contracts (ENH-013 006, FR-006.9, MA6).

``tests/support/answer_enums.py`` lists them. For each row of a ``vendored`` app the contract's
``enum`` at the row's pointer is read through ``answer_contracts`` and the row's mode is held
(``partition``: equal; ``subset``: contained). A ``hand`` app's rows wait for its contract and are
reported as waiting. Always, whatever the state: every constant resolves to strings, the constants
of a ``partition`` are disjoint, and the coverage walk below finds every string-set constant a
comparison in ``src/miassist/playbooks`` or ``adapters`` reads, each in a row or ``EXEMPT`` (M15
drops a row and turns it red).
"""

from __future__ import annotations

import ast
import importlib
import sys
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import miassist.tools  # noqa: F401 - the tool registry first: the playbook modules import in its order
from tests.support import answer_contracts as ac
from tests.support import synthetic_contract as sc
from tests.support.answer_enums import ANSWER_ENUMS, EXEMPT, AnswerEnum

SRC = Path(__file__).resolve().parents[2] / "src" / "miassist"
SCANNED = ("playbooks", "adapters")


def resolve(dotted: str) -> tuple[Any, frozenset[str]]:
    """The object a row names and its string values (a mapping's keys; ``NAME[key]``'s value)."""
    key = None
    if dotted.endswith("]"):
        dotted, key = dotted[:-1].split("[")
    module, name = dotted.rsplit(".", 1)
    value = getattr(importlib.import_module(module), name)
    obj = value
    if key is not None:
        value = value[key]
    values = list(value.keys() if isinstance(value, Mapping) else value)
    assert values and all(isinstance(v, str) for v in values), dotted
    return obj, frozenset(str(v) for v in values)


def enum_at(schema: Any, pointer: str) -> set[str]:
    """The values the answer can hold at ``pointer`` (``enum`` and ``const``, through unions)."""
    nodes = [schema]
    for step in [s for s in pointer.split("/") if s]:
        nodes = [n for node in nodes for n in _branches(node)]
        nodes = [
            (n.get("items") if step == "[]" else (n.get("properties") or {}).get(step))
            for n in nodes
        ]
        nodes = [n for n in nodes if isinstance(n, Mapping)]
    found: set[str] = set()
    for node in [b for n in nodes for b in _branches(n)]:
        found |= {str(v) for v in node.get("enum", []) if v is not None}
        if "const" in node and node["const"] is not None:
            found.add(str(node["const"]))
    return found


def _branches(node: Any) -> list[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        return []
    out = [node]
    for key in ("anyOf", "oneOf", "allOf"):
        out += [b for sub in node.get(key, []) for b in _branches(sub)]
    return out


def contract_enum(row: AnswerEnum) -> set[str]:
    method, template = row.route.split(" ", 1)
    found = enum_at(ac.resolved(row.app, method, template, row.status), row.pointer)
    assert found, f"{row.app} {row.route} {row.status} {row.pointer}: the contract names no enum"
    return found


def held(row: AnswerEnum) -> list[str]:
    """What is wrong with ``row`` against its app's contract (empty: it holds)."""
    values = [resolve(c)[1] for c in row.constants]
    union = frozenset().union(*values)
    enum = contract_enum(row)
    if row.mode == "partition":
        return [] if union == enum else [f"{row.constants} name {sorted(union)}; {sorted(enum)}"]
    peers = [row] + [
        r for r in ANSWER_ENUMS if r.constants == row.constants and r != row and ac.vendored(r.app)
    ]
    allowed = set().union(*(contract_enum(r) for r in peers))
    extra = sorted(union - allowed)
    return [f"{row.constants} hold {extra}, which {row.app} never sends"] if extra else []


@pytest.mark.parametrize(
    "row", ANSWER_ENUMS, ids=lambda r: f"{r.app}{r.pointer}-{r.constants[0].rsplit('.', 1)[1]}"
)
def test_each_enum_matches_its_contract(row: AnswerEnum) -> None:
    if not ac.vendored(row.app):
        pytest.skip(f"{row.app} is hand: its rows wait for its contract ({row.reason or row.mode})")
    waiting = sorted(
        {r.app for r in ANSWER_ENUMS if r.constants == row.constants and not ac.vendored(r.app)}
    )
    if waiting:
        # A set read against several apps' fields (``OPEN``) is held to their union, which is
        # known only once each is vendored; the field must still name an enum here.
        assert contract_enum(row)
        pytest.skip(f"{row.constants} span {waiting} too, still hand: the union waits for them")
    assert held(row) == []


@pytest.mark.parametrize("row", ANSWER_ENUMS, ids=lambda r: f"{r.app}{r.pointer}")
def test_each_row_names_strings_and_a_registered_route(row: AnswerEnum) -> None:
    from miassist.adapters.routes import ROUTES

    values = [resolve(c)[1] for c in row.constants]
    if row.mode == "partition":
        total = sum(len(v) for v in values)
        assert total == len(frozenset().union(*values)), f"{row.constants} overlap"
    else:
        assert row.reason, f"a subset row says why it is not a partition: {row}"
    assert (row.app, row.route) in {(r.app, f"{r.method} {r.path}") for r in ROUTES}, row


def comment_above(dotted: str) -> str:
    """The ``#`` comment lines directly above ``NAME``'s assignment in its module."""
    module, name = dotted.split("[")[0].rsplit(".", 1)
    lines = Path(importlib.import_module(module).__file__ or "").read_text().splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith((f"{name}:", f"{name} =")))
    above: list[str] = []
    for line in reversed(lines[:at]):
        if not line.startswith("#"):
            break
        above.insert(0, line)
    return "\n".join(above)


@pytest.mark.parametrize("row", [r for r in ANSWER_ENUMS if ac.vendored(r.app)], ids=str)
def test_a_vendored_rows_constants_cite_the_contract(row: AnswerEnum) -> None:
    """FR-006.9: each constant's citation names the contract, not a sibling's code line."""
    for constant in row.constants:
        text = comment_above(constant)
        assert ac.FILES[row.app] in text, f"{constant}'s comment does not cite {ac.FILES[row.app]}"


# -- the coverage walk (FR-006.9 AC) -------------------------------------------------------------


def read_constants() -> dict[str, tuple[str, int]]:
    """Every module-level string-set constant (a set, tuple or list of strings, or a mapping with
    string keys) that an ``in``/``not in`` comparison, a subscript or a ``.get`` in
    ``playbooks/`` or ``adapters/`` reads: its defining ``module.NAME`` and one reading site."""
    found: dict[str, tuple[str, int]] = {}
    for sub in SCANNED:
        for path in sorted((SRC / sub).rglob("*.py")):
            rel = path.relative_to(SRC)
            module = ".".join(("miassist", *rel.with_suffix("").parts)).removesuffix(".__init__")
            mod = importlib.import_module(module)
            for node in ast.walk(ast.parse(path.read_text())):
                for name, line, kind in _reads(node):
                    value = getattr(mod, name, None)
                    if not _string_set(value) or (kind != "in" and not isinstance(value, Mapping)):
                        continue
                    owner = _owner(mod, name, value)
                    found.setdefault(owner, (rel.as_posix(), line))
    return found


def _reads(node: ast.AST) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    if isinstance(node, ast.Compare):
        for op, side in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, (ast.In, ast.NotIn)):
                out += [
                    (n.id, node.lineno, "in") for n in ast.walk(side) if isinstance(n, ast.Name)
                ]
    elif isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp):
        # ``known = A | B | C``, then ``status in known``: each constant of the union is read.
        out += [(n.id, node.lineno, "in") for n in ast.walk(node.value) if isinstance(n, ast.Name)]
    elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        out.append((node.value.id, node.lineno, "sub"))
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
    ):
        out.append((node.func.value.id, node.lineno, "get"))
    return out


def _string_set(value: Any) -> bool:
    if not isinstance(value, (set, frozenset, tuple, list, Mapping)) or not value:
        return False
    return all(isinstance(v, str) for v in value)


def _owner(mod: Any, name: str, value: Any) -> str:
    """``module.NAME`` where ``value`` is defined (an imported constant is its owner's)."""
    for candidate in (mod.__name__, *sorted(_imported_from(mod))):
        owner = importlib.import_module(candidate)
        if getattr(owner, name, None) is value and name in _assigned(owner):
            return f"{candidate}.{name}"
    return f"{mod.__name__}.{name}"


def _imported_from(mod: Any) -> set[str]:
    tree = ast.parse(Path(mod.__file__).read_text())
    return {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}


def _assigned(mod: Any) -> set[str]:
    tree = ast.parse(Path(mod.__file__).read_text())
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def named() -> set[str]:
    return {c.split("[")[0] for row in ANSWER_ENUMS for c in row.constants}


def test_every_read_constant_is_a_row_or_exempt() -> None:
    """FR-006.9 AC: the table names every constant in ``src/`` a sibling's answer field is
    compared with (M15 drops a row)."""
    found = read_constants()
    missing = {k: v for k, v in found.items() if k not in named() and k not in EXEMPT}
    assert not missing, (
        "a comparison reads a string-set constant that tests/support/answer_enums.py does not "
        f"name (add a row, or an EXEMPT entry with why): {missing}"
    )


def test_every_row_and_exemption_is_still_read() -> None:
    """The other direction: a row none of whose constants a comparison reads, or an exemption no
    comparison reads, is stale. (A partition may hold a constant nothing reads: ``JOB_RUNNING``
    names the statuses that are waited on, so the partition is whole.)"""
    found = set(read_constants())
    stale = [r for r in ANSWER_ENUMS if not {c.split("[")[0] for c in r.constants} & found]
    assert not stale, stale
    assert not (set(EXEMPT) - found), sorted(set(EXEMPT) - found)


# -- the check itself, on the synthetic contract --------------------------------------------------


def test_a_partition_and_a_subset_are_held_against_a_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``held`` is proven before any app is vendored: ``ProbeStatus.served_weights`` is
    ``["base", "attached"]`` in the synthetic contract."""
    monkeypatch.setitem(ac.LOADED, "miserver", ac.Contract(sc.APP, sc.document()))
    monkeypatch.setitem(ac.ANSWER_SOURCES, "miserver", "vendored")
    fake = types.ModuleType("_enum_case")
    fake.BASE = frozenset({"base"})  # type: ignore[attr-defined]
    fake.ATTACHED = frozenset({"attached"})  # type: ignore[attr-defined]
    fake.GUESS = frozenset({"base", "lora"})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_enum_case", fake)
    route = ("miserver", "GET /api/probes/status", 200, "/data/served_weights")
    part = AnswerEnum(*route, ("_enum_case.BASE", "_enum_case.ATTACHED"), "partition")
    assert held(part) == []
    assert held(AnswerEnum(*route, ("_enum_case.BASE",), "partition")) != []
    assert held(AnswerEnum(*route, ("_enum_case.BASE",), "subset", "x")) == []
    assert held(AnswerEnum(*route, ("_enum_case.GUESS",), "subset", "x")) == [
        "('_enum_case.GUESS',) hold ['lora'], which miserver never sends"
    ]
