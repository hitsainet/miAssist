"""Each app's answer source, held to its files (ENH-013 006; FR-006.1 to FR-006.3, FR-006.6).

- **The state (FR-006.3, MA4).** ``answer_contracts.ANSWER_SOURCES`` names each of the four apps
  ``hand`` or ``vendored``. A ``vendored`` app has its contract in ``docs/schemas/`` (kind and digest
  checked), an ownership entry and a README row, and NO hand record: no ``apps.<app>`` block in
  ``responses.json`` and no ``response_sources/<app>.json``. A ``hand`` app has both and no copy.
  M5 (miDataworks ``vendored`` without its copy) turns this red.
- **The pins (FR-006.2).** A ``vendored`` app's OpenAPI snapshot is pinned at the commit its README
  row says the contract was copied at.
- **The external documents (AT3).** Each contract's ``external`` ``$id``s are listed here, so a new
  one is a reviewed change; each is read as an open object.
- **The registry walk (FR-006.6).** Every registered route (``miassist.adapters.routes.ROUTES``,
  the live registry, never source text) reads its success shapes from the source its app's state
  names: ``contract`` for a ``vendored`` app, never ``responses.json`` or the snapshot; and for a
  ``hand`` app never the contract. The walk counts every registered route (M11 drops one from it).
  The status each fake answers is checked against the same lookup at every playbook test's teardown
  (``shapes.ShapedFakeApp``), so a fake status the contract lacks fails there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from miassist.adapters.routes import ROUTES
from tests.contract.schema_ownership import OWNERSHIP, Vendored
from tests.support import answer_contracts as ac
from tests.support import response_shapes as rs
from tests.support import shapes

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "tests" / "fixtures" / "openapi" / "response_sources"
README = ROOT / "docs" / "schemas" / "README.md"

#: The state each push leaves (006-1 flips miServer, 006-2 miDataworks, 006-3 miWorkbench, 006-4
#: miForge). A change to ``ANSWER_SOURCES`` changes this line too, in the same reviewed commit.
STATE_AT_THIS_PUSH = {
    "miserver": "vendored",
    "midataworks": "hand",
    "miworkbench": "hand",
    "miforge": "hand",
}
#: Each vendored contract's ``external`` ``$id``s (AT3), filled as each is vendored.
EXTERNAL_IDS: dict[str, tuple[str, ...]] = {
    "miserver": (
        "https://hitsai.net/schemas/mistudio/behaviour-verdict-v1.json",
        "https://raw.githubusercontent.com/hitsainet/miDataworks/main/docs/schemas/midataworks-rule-set-v1.json",
        "https://raw.githubusercontent.com/hitsainet/miStudio/main/docs/schemas/circuit-definition-v1.json",
        "https://raw.githubusercontent.com/hitsainet/miStudio/main/docs/schemas/cluster-definition-v1.json",
    ),
}


def test_the_state_table() -> None:
    assert tuple(ac.ANSWER_SOURCES) == ac.APPS
    assert set(ac.ANSWER_SOURCES.values()) <= {"hand", "vendored"}
    assert ac.ANSWER_SOURCES == STATE_AT_THIS_PUSH


@pytest.mark.parametrize("app", ac.APPS)
def test_a_state_is_held_to_its_files(app: str) -> None:
    hand_block = app in rs.vendored()["apps"]
    overlay = (SOURCES / f"{app}.json").is_file()
    copy = ac.path(app).is_file()
    if ac.vendored(app):
        assert copy, f"{app} is vendored but {ac.path(app)} is missing"
        assert ac.contract(app).doc == ac.load(app)
        assert isinstance(OWNERSHIP.get(ac.FILES[app]), Vendored), f"{ac.FILES[app]} has no entry"
        assert not hand_block, f"{app} is vendored but responses.json still holds apps.{app}"
        assert not overlay, f"{app} is vendored but response_sources/{app}.json still exists"
    else:
        assert hand_block and overlay, f"{app} is hand: its hand records are its only shapes"
        assert not copy, f"{app} is hand but {ac.path(app)} exists: flip its state, or remove it"


def test_a_copy_row_is_read() -> None:
    """The row reader the pin tests use."""
    row = (
        "| `miserver-answers-v1.json` | vendored | miServer | copied at a8ff9281, revision 1; 182 |"
    )
    assert ac.copied(row) == ("a8ff9281", 1)
    with pytest.raises(ac.ContractError, match="does not say"):
        ac.copied("| `x.json` | vendored | miServer | copied from a branch |")


def test_the_shape_generator_refuses_a_vendored_app() -> None:
    """MA4: ``scripts/snapshot_shapes.py`` never writes hand records for a vendored app again; it
    refuses before it reads anything (so no sibling is needed)."""
    from scripts import snapshot_shapes

    vendored = [a for a in ac.APPS if ac.vendored(a)]
    assert vendored
    for app in vendored:
        with pytest.raises(SystemExit, match=f"{app} is vendored"):
            snapshot_shapes.main(["--app", app])


@pytest.mark.parametrize("app", [a for a in ac.APPS if ac.vendored(a)])
def test_a_vendored_snapshot_is_pinned_at_its_contract_commit(app: str) -> None:
    """FR-006.2 AC: the snapshot and the copy come from ONE producer commit (M3 moves one)."""
    commit, revision = ac.copied(ac.readme_row(ac.FILES[app]))
    assert str(rs.snapshot(app)["commit"]) == commit
    assert ac.contract(app).doc.get("revision") == revision


def test_each_vendored_contract_lists_its_external_documents() -> None:
    vendored = [a for a in ac.APPS if ac.vendored(a)]
    assert sorted(EXTERNAL_IDS) == vendored
    for app in vendored:
        contract = ac.contract(app)
        assert tuple(sorted(contract.external)) == EXTERNAL_IDS[app]
        for uri in contract.external:
            assert contract.inline({"$ref": uri}) == {"type": "object"}


# -- the registry walk (FR-006.6) ----------------------------------------------------------------


def success_statuses(route: Any) -> list[str]:
    op = rs.snapshot(route.app).get("paths", {}).get(route.path, {}).get(route.method.lower(), {})
    return sorted(s for s in op.get("responses", {}) if s.startswith("2"))


def walk(routes: Any) -> list[tuple[str, str, str, str]]:
    """``(route id, status, source, problem)`` for each registered route's success statuses."""
    seen: list[tuple[str, str, str, str]] = []
    for route in routes:
        statuses = success_statuses(route)
        if ac.vendored(route.app) and not statuses:
            seen.append((route.id, "", "", "no success status to read"))
        for status in statuses or [""]:
            if not status:
                seen.append((route.id, "", "", ""))
                continue
            source = rs.shape_source(route.app, route.method, route.path, status)
            want = {"contract"} if ac.vendored(route.app) else {"responses.json", "snapshot"}
            problem = "" if source in want else f"{source} for a {ac.ANSWER_SOURCES[route.app]} app"
            if (
                ac.vendored(route.app)
                and rs.schema_for(route.app, route.method, route.path, status) is None
            ):
                problem = problem or "the contract has no such answer"
            seen.append((route.id, status, source, problem))
    return seen


def test_every_registered_route_reads_its_apps_source() -> None:
    walked = walk(ROUTES)
    problems = [w for w in walked if w[3]]
    assert not problems, problems
    assert len({w[0] for w in walked}) == len(ROUTES) == len({r.id for r in ROUTES})
    vendored = [r for r in ROUTES if ac.vendored(r.app)]
    assert len({w[0] for w in walked if w[2] == "contract"}) == len(vendored)


def test_the_walk_counts_what_it_reads() -> None:
    """96 routes on 2026-11-25 (BRD §1); a smaller registry is a change to review, not a pass."""
    assert len(ROUTES) >= 96
    by_app = {app: sum(1 for r in ROUTES if r.app == app) for app in ac.APPS}
    assert by_app == {"miserver": 16, "midataworks": 37, "miworkbench": 37, "miforge": 6}, by_app


# -- the FPRD's cases on miServer's real contract (006-1; FR-006.4, FR-006.5) ----------------------


def _data(shape: Any) -> Any:
    return next(b for b in shape["properties"]["data"]["anyOf"] if b.get("type") != "null")


def test_miservers_status_answer_reads_whole() -> None:
    """FR-006.4 AC: ``GET /api/probes/status`` is ``ApiResponse[ProbeStatus]`` with every reference
    resolved; an ``excluded`` route has no shape."""
    assert ac.vendored("miserver")
    shape = rs.schema_for("miserver", "GET", "/api/probes/status", 200)
    assert (
        shape is not None
        and shape["title"] == "ApiResponse[ProbeStatus]"
        and "$ref" not in str(shape)
    )
    assert rs.schema_for("miserver", "GET", "/api/health/metrics/prometheus", 200) is None


def test_miservers_strict_form_holds_fakes_to_the_real_shapes() -> None:
    """FR-006.5 ACs on the real contract: ``results_total`` is invented in an import's
    ``ProbeSummary`` and dropped from a list's ``ProbeListItem``; a chat completion may omit
    ``system_fingerprint``; an approval's ``summary`` map takes a new key."""
    imported = _data(rs.schema_for("miserver", "POST", "/api/probes/import", 200))
    summary = shapes.fill(imported, id="evalfx-p", name="p")
    assert rs.check(imported, {**summary, "results_total": 1}) == [
        "$.results_total: invented (the app never sends it)"
    ]
    item = _data(rs.schema_for("miserver", "GET", "/api/probes", 200))["items"]
    row = shapes.fill(item, id="evalfx-p", name="p")
    assert rs.check(item, {k: v for k, v in row.items() if k != "results_total"}) == [
        "$.results_total: dropped (the app always sends it)"
    ]
    chat = rs.schema_for("miserver", "POST", "/v1/chat/completions", 200)
    answer = shapes.fill(chat)
    assert "system_fingerprint" not in answer and rs.check(chat, answer) == []
    approval = _data(rs.schema_for("miserver", "GET", "/api/approvals/{approval_id}", 200))
    assert approval["properties"]["summary"]["additionalProperties"] is True
