"""Every sibling error code ``src/`` branches on is in one table (ENH-013 006, FR-006.7, MA3).

``tests/support/error_codes.py`` holds the codes. This test walks the syntax tree of every module
under ``src/miassist/`` (the code itself, not a text search) and collects each literal compared with
a code:
- ``==``, ``!=``, ``in`` or ``not in`` between a code and a string, a literal set, tuple or list of
  strings, or a module-level constant holding them (read from the imported module);
- ``<code>.endswith("...")`` or ``.startswith("...")``.

A code is ``<x>.code`` (and any string method on it, ``removeprefix``), ``<x>.get("code")``,
``<x>["code"]``, a call to a reader in ``READERS``, a name called ``code``, or a name bound from any
of these in the same function. Each literal found must be a row of ``ERROR_CODES_RELIED_ON``, an
``OWN_CODES`` entry or a ``DEAD_CODES`` entry; and each row must be found at the file it names, so a
row cannot outlive its comparison. M13 adds a code comparison with no row and turns this red.

The envelope half of FR-006.7: an error answer a fake gives for a ``vendored`` app is checked
against that contract's ``errors`` envelope (``shapes.ShapedFakeApp``); proven on the synthetic
contract until 006-1 vendors miServer.
"""

from __future__ import annotations

import ast
import importlib
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support import answer_contracts as ac
from tests.support import shapes
from tests.support import synthetic_contract as sc
from tests.support.error_codes import DEAD_CODES, ERROR_CODES_RELIED_ON, OWN_CODES

SRC = Path(__file__).resolve().parents[2] / "src" / "miassist"
#: Functions that return an app's code (or the field that stands for it) from an answer.
READERS = frozenset({"refused_as", "_envelope"})
#: String methods that keep a code a code.
STR_METHODS = frozenset({"removeprefix", "removesuffix", "lower", "upper", "strip"})
OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)


@dataclass(frozen=True)
class Found:
    file: str
    line: int
    code: str
    how: str  # "exact" or "suffix" / "prefix"
    via: str = ""  # the READERS function the code came from, if any


def _str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class Walk(ast.NodeVisitor):
    def __init__(self, module: str, file: str) -> None:
        self.module, self.file = module, file
        self.bound: list[set[str]] = [set()]
        self.found: list[Found] = []

    def is_code(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute):
            return node.attr == "code"
        if isinstance(node, ast.Name):
            return node.id == "code" or node.id in self.bound[-1]
        if isinstance(node, ast.Subscript):
            return _str(node.slice) == "code"
        if isinstance(node, ast.IfExp):
            return self.is_code(node.body) or self.is_code(node.orelse)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                return func.id in READERS
            if isinstance(func, ast.Attribute):
                if func.attr == "get" and node.args and _str(node.args[0]) == "code":
                    return True
                return func.attr in STR_METHODS and self.is_code(func.value)
        return False

    @staticmethod
    def reader(node: ast.AST) -> str:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id if node.func.id in READERS else ""
        return ""

    def literals(self, node: ast.AST) -> list[str] | None:
        if (one := _str(node)) is not None:
            return [one]
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            found = [_str(e) for e in node.elts]
            return [f for f in found if f is not None] if all(found) else None
        if isinstance(node, ast.Name):
            value = getattr(importlib.import_module(self.module), node.id, None)
            if (
                isinstance(value, (set, frozenset, tuple, list))
                and value
                and all(isinstance(v, str) for v in value)
            ):
                return sorted(value)
        return None

    def _scope(self, node: ast.AST) -> None:
        self.bound.append(set())
        self.generic_visit(node)
        self.bound.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.is_code(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.bound[-1].add(target.id)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        sides = [node.left, *node.comparators]
        for op, (a, b) in zip(node.ops, itertools.pairwise(sides), strict=True):
            if not isinstance(op, OPS):
                continue
            # ``code in {...}`` reads a code; ``"x" in code`` is a substring test of a text.
            pairs = ((a, b),) if isinstance(op, (ast.In, ast.NotIn)) else ((a, b), (b, a))
            for code, other in pairs:
                if self.is_code(code) and (found := self.literals(other)) is not None:
                    via = self.reader(code)
                    self.found += [Found(self.file, node.lineno, f, "exact", via) for f in found]
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("endswith", "startswith")
            and self.is_code(func.value)
            and node.args
            and (lit := _str(node.args[0])) is not None
        ):
            how = "suffix" if func.attr == "endswith" else "prefix"
            self.found.append(Found(self.file, node.lineno, lit, how))
        self.generic_visit(node)


def compared() -> list[Found]:
    found: list[Found] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        module = ".".join(("miassist", *rel.with_suffix("").parts)).removesuffix(".__init__")
        walk = Walk(module, rel.as_posix())
        walk.visit(ast.parse(path.read_text(), filename=str(path)))
        found += walk.found
    return found


def sites(found: list[Found]) -> Iterator[str]:
    for f in found:
        yield f"{f.file}:{f.line} {f.code!r} ({f.how})"


def test_the_walk_finds_the_known_comparisons() -> None:
    """The walk itself works: each form it must read is found (a walk that finds nothing would
    pass the coverage test below vacuously)."""
    found = {(f.file, f.code, f.how) for f in compared()}
    assert ("adapters/miworkbench.py", "consumed", "exact") in found  # a READERS call
    assert ("adapters/miworkbench.py", "mismatch", "exact") in found  # a name bound from .code
    assert ("playbooks/detector_probe/actions.py", "NAME_CONFLICT", "exact") in found  # .get
    assert ("playbooks/dataset/actions.py", "search_timeout", "exact") in found  # in CONSTANT
    assert ("playbooks/steering/actions.py", "model_not_resident", "suffix") in found
    assert ("results/app_answers.py", "import_confirmation_required", "exact") in found


def test_every_compared_code_is_in_the_table() -> None:
    """FR-006.7 AC: the table names every code literal ``src/`` compares a sibling's code with."""
    rows = {r.code for r in ERROR_CODES_RELIED_ON}
    unknown = [
        f
        for f in compared()
        if f.code not in rows and f.code not in OWN_CODES and f.code not in DEAD_CODES
    ]
    assert not unknown, (
        "src/ compares a code no table names; add a row to tests/support/error_codes.py "
        f"(or OWN_CODES / DEAD_CODES with why): {list(sites(unknown))}"
    )


def test_every_row_is_compared_where_it_says() -> None:
    """The other direction: a row whose comparison is gone, or moved file, is stale."""
    found = {(f.file, f.code, "suffix" if f.how == "suffix" else "exact") for f in compared()}
    stale = [
        r for r in ERROR_CODES_RELIED_ON if (r.src.split(":")[0], r.code, r.match) not in found
    ]
    assert not stale, stale
    for name in (*OWN_CODES, *DEAD_CODES):
        assert any(f.code == name for f in compared()), f"{name} is listed but compared nowhere"


def test_a_status_row_is_read_from_the_status() -> None:
    """MAP-2 (PRE-006): miWorkbench's spent-approval 409 carries ``detail.status``, never a code,
    so its row must be compared through ``refused_as`` (which reads that status); a comparison of
    the answer's ``code`` with ``consumed`` never matches (M22)."""
    rows = [r for r in ERROR_CODES_RELIED_ON if r.where == "detail.status"]
    assert rows
    for row in rows:
        at = [f for f in compared() if f.file == row.src.split(":")[0] and f.code == row.code]
        assert at and all(f.via == "refused_as" for f in at), (row, at)


def test_every_row_names_a_harness_and_a_registered_route() -> None:
    from miassist.adapters.routes import ROUTES

    harnesses = Path(__file__).resolve().parents[1] / "cross_repo" / "error_code_harnesses"
    registered = {(r.app, f"{r.method} {r.path}") for r in ROUTES}
    for row in ERROR_CODES_RELIED_ON:
        assert (harnesses / row.harness).is_file(), row
        assert (row.app, row.route) in registered, row
    assert {p.name for p in harnesses.glob("*.py")} == {r.harness for r in ERROR_CODES_RELIED_ON}


# -- the envelope (FR-006.7) on the synthetic contract ------------------------------------------


@pytest.fixture
def miserver_vendored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ac.LOADED, "miserver", ac.Contract(sc.APP, sc.document()))
    monkeypatch.setitem(ac.ANSWER_SOURCES, "miserver", "vendored")


def answered(
    status: int, body: Any, path: str = "/api/probes/status", app: str = "miserver"
) -> list[str]:
    from miassist.adapters.base import HEADERS

    fake = shapes.ShapedFakeApp(app)
    fake.on("GET", path, lambda _r: httpx.Response(status, json=body))
    name, value = HEADERS[app]
    response = fake.handle(httpx.Request("GET", f"http://{app}{path}", headers={name: value}))
    shapes.LIVE.remove(fake)
    assert response.status_code == status and fake.calls("GET", path), "the fake answered it"
    return fake.violations


def test_a_vendored_apps_refusal_is_checked_against_its_envelope(miserver_vendored: None) -> None:
    good = {"success": False, "data": None, "error": {"code": "PROBE_NOT_FOUND", "message": "m"}}
    assert answered(404, good) == []
    assert answered(404, {**good, "detail": "x"}) == [
        "miserver GET /api/probes/status 404 $.detail: invented (the app never sends it)"
    ]
    assert answered(422, {"error": {"code": "x"}}) != []


def test_an_envelope_is_chosen_by_path() -> None:
    assert ac.envelope_for("miserver", "/v1/chat/completions") == "openai"
    assert ac.envelope_for("miserver", "/api/probes/import") == "management"
    assert ac.envelope_for("midataworks", "/api/v1/jobs/{job_id}") == "app"
    with pytest.raises(KeyError):
        ac.envelope_for("miworkbench", "/api/v1/x")


def test_a_hand_apps_refusal_is_not_checked() -> None:
    """Until an app is vendored its fakes' error answers are hand-built (``fake.error``) and stay
    unchecked, as before 006."""
    assert not ac.vendored("midataworks")
    assert answered(404, {"anything": 1}, "/api/v1/approvals", "midataworks") == []
