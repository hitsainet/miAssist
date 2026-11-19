"""miServer's hand-derived probe shapes name the fields miServer's own code sends (final re-vendor,
2026-11-17).

``responses.json`` holds miServer's probe answers as hand-derived, CLOSED shapes (miServer answers an
open ``ApiResponse``/``PageResponse``), and ``tests/cross_repo/test_response_shapes_live.py`` checks
only the generator's entries. So a field miServer adds (043's ``derived_from`` on every probe summary
and ``served_weights`` on the probe status) left those shapes stale while every test stayed green: a
fake built from them omits the field by construction. This test runs miServer's OWN serialisers in
its interpreter, from a ``git archive`` of the shapes' commit (nothing is written in the sibling),
and compares the keys they emit with the hand shapes' properties. Skips loudly when miServer is
absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from typing import Any

import pytest
from scripts import snapshot_openapi as snap

from tests.support import response_shapes as rs
from tests.support import siblings

pytestmark = pytest.mark.cross_repo

#: Run in miServer's interpreter: the keys of one probe summary (a mock row; only the keys are
#: read), the keys the list route adds for a probe without results, and the served-weights fact.
PROBE = r"""
import json, sys
sys.path.insert(0, ".")
from unittest.mock import MagicMock
from miserver.api.routes.management import probes
from miserver.services.resident_identity import NOTHING_LOADED
row = MagicMock()
row.definition = {}
row.rung = 0
row.threshold_revision = 1
sys.stdout.write("@@KEYS@@" + json.dumps({
    "summary": sorted(probes._probe_summary(row)),
    "totals": sorted(probes.NO_RESULTS),
    "served_weights": sorted(NOTHING_LOADED.as_dict()),
}))
"""


@cache
def live_keys() -> dict[str, list[str]]:
    root = siblings.require_root(siblings.MISERVER, "miServer's probe shapes cannot be compared")
    commit = rs.vendored()["apps"]["miserver"]["commit"]
    tree, _ = snap.export(snap.RECIPES["miserver"]["folder"], commit, repo=root)
    result = subprocess.run(
        [str(snap.interpreter("miserver", root)), "-B", "-c", PROBE],
        cwd=tree / snap.RECIPES["miserver"]["cwd"],
        env={**os.environ, **snap.IMPORT_ENV},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "@@KEYS@@" in result.stdout, result.stderr[-2000:]
    loaded: dict[str, list[str]] = json.loads(result.stdout.split("@@KEYS@@", 1)[1])
    return loaded


def hand(route: str) -> Any:
    entry = rs.vendored()["apps"]["miserver"]["routes"][route]["200"]
    assert "generated" not in entry, f"{route} is no longer hand-derived: this test is moot"
    return entry["schema"]["properties"]["data"]


def test_the_import_answer_names_the_summarys_fields() -> None:
    data = hand("POST /api/probes/import")
    assert sorted(data["properties"]) == live_keys()["summary"]
    assert sorted(data["required"]) == live_keys()["summary"]


def test_the_list_answer_names_the_summarys_fields_and_the_totals() -> None:
    item = hand("GET /api/probes")["items"]
    expected = sorted({*live_keys()["summary"], *live_keys()["totals"]})
    assert sorted(item["properties"]) == expected
    assert sorted(item["required"]) == expected


def test_the_status_answer_names_the_served_weights_fact() -> None:
    data = hand("GET /api/probes/status")
    assert "served_weights" in data["required"]
    served = data["properties"]["served_weights"]
    assert sorted(served["properties"]) == live_keys()["served_weights"]
    assert sorted(served["required"]) == live_keys()["served_weights"]
