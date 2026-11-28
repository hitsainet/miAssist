"""The hand records left per app, until BR-9 closes (ENH-013 006; FR-006.13, MA7).

A hand record is a status entry under ``apps.<app>.routes`` in
``tests/fixtures/openapi/responses.json``: hand-written, or generated from a hand overlay in
``response_sources/<app>.json``. Both kinds count. A ``vendored`` app has none (FR-006.3). A
``hand`` app's count equals ``LEFT`` (printed), and ``LEFT`` may only fall from ``BASELINE``, the
count on 2026-11-25 (BRD-MIASSIST-SHAPES-001 §8): a new hand record for an app still on hand
records turns this red (M19). When the count falls, lower ``LEFT`` in the same commit.

This is the open debt that 006-1 to 006-4 pay off; 006-4 adds the removal test (FR-006.12).
"""

from __future__ import annotations

from tests.support import answer_contracts as ac
from tests.support import response_shapes as rs

#: miForge's 7 became 9 on main before this guard landed there: ``2f541bf`` (2026-11-27) added
#: code-cited overlays for ``GET /api/v1/checkpoints`` and ``GET /api/v1/runs``, matching miForge's
#: own typed answers. Re-derived when 006-1 was rebased onto it (2026-11-28); 006-4 retires them.
BASELINE = {"miserver": 18, "midataworks": 34, "miworkbench": 44, "miforge": 9}
#: The entries left now, per app; a vendored app's is 0.
LEFT = {"miserver": 0, "midataworks": 34, "miworkbench": 44, "miforge": 9}


def counts() -> dict[str, int]:
    apps = rs.vendored()["apps"]
    return {
        app: sum(
            1
            for statuses in apps.get(app, {}).get("routes", {}).values()
            for status in statuses
            if not status.startswith("x-")
        )
        for app in ac.APPS
    }


def test_the_hand_records_left_per_app() -> None:
    found = counts()
    print("hand records left:", {a: (ac.ANSWER_SOURCES[a], found[a]) for a in ac.APPS})
    assert found == LEFT, f"responses.json holds {found}; LEFT says {LEFT}"
    for app in ac.APPS:
        assert LEFT[app] <= BASELINE[app], f"{app}: a hand-record count may only fall"
        if ac.vendored(app):
            assert LEFT[app] == 0, f"{app} is vendored: it has no hand record"
