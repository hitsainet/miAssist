"""No decide route, ever (ADR-006; 001 FTASKS 5.6): the live registry and a source guard."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Route
from miassist.adapters.routes import DECIDE_SUFFIXES, ROUTES, RouteRegistry

SRC = Path(__file__).resolve().parents[2] / "src"
DECIDE = re.compile(r"""["'][^"']*/(approve|deny|reject|approve-batch|revoke)["']""")


def test_registry() -> None:
    assert len(ROUTES) > 10
    for route in ROUTES:
        assert not route.path.endswith(DECIDE_SUFFIXES), route.id


def test_registering_a_decide_route_fails() -> None:
    route = Route(
        "midataworks.approve",
        "midataworks",
        "POST",
        "/api/v1/approvals/{id}/approve",
        GateClass.APP_GATED,
        "never",
    )
    with pytest.raises(ProgrammingError):
        RouteRegistry((route,))


def decide_literals(source: str) -> list[str]:
    return [m.group(0) for m in DECIDE.finditer(source)]


def test_source_guard() -> None:
    hits = {
        str(p.relative_to(SRC)): decide_literals(p.read_text())
        for p in SRC.rglob("*.py")
        if p.name != "routes.py"
    }
    assert not {k: v for k, v in hits.items() if v}


@pytest.mark.parametrize(
    "source",
    ['P = "/api/v1/approvals/{id}/approve"\n', "x = '/x/deny'\n", 'y = "/a/approve-batch"\n'],
)
def test_source_guard_self_test(source: str) -> None:
    assert decide_literals(source)


@pytest.mark.parametrize("suffix", DECIDE_SUFFIXES)
@pytest.mark.parametrize("app", ["miworkbench", "miserver", "midataworks", "miforge"])
def test_every_decide_suffix_refused_by_name(app: str, suffix: str) -> None:
    """R1 review fix (OR1-001-8, N-4), 2026-11-16: the any.decide never-route is the one rule (the
    registration's second suffix check was redundant and is gone); each suffix is refused by it."""
    from miassist.adapters.base import GateClass, ProgrammingError, Route

    route = Route(
        f"{app}.fixture", app, "POST", f"/api/v1/approvals/{{id}}{suffix}", GateClass.APP_GATED, "x"
    )
    with pytest.raises(ProgrammingError, match=r"never-route \(any\.decide\)"):
        RouteRegistry((route,))


@pytest.mark.parametrize(
    ("app", "path", "never_id"),
    [
        ("midataworks", "/api/v1/code-rules/approvals/{code_sha256}/revoke", "any.decide"),
        ("midataworks", "/api/v1/operators/allowlist/revoke", "any.decide"),
        ("miworkbench", "/api/v1/code-rules/{code_sha256}/revoke", "any.decide"),
        ("midataworks", "/api/v1/approvals/{approval_id}/archive", "any.approval_archive"),
        ("midataworks", "/api/v1/approvals/{approval_id}/unarchive", "any.approval_archive"),
    ],
)
def test_revoke_and_archive_routes_are_refused(app: str, path: str, never_id: str) -> None:
    """R2 review fix (OR2-001-9), 2026-11-16: the apps' revoke and approval-archive routes, by
    their exact paths in the route index, are never-routes; registering one fails."""
    route = Route(f"{app}.fixture", app, "POST", path, GateClass.APP_GATED, "x")
    with pytest.raises(ProgrammingError, match=rf"never-route \({re.escape(never_id)}\)"):
        RouteRegistry((route,))
