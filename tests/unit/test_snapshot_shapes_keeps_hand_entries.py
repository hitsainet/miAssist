"""``scripts.snapshot_shapes.write`` keeps a hand-derived entry (003's) and replaces only its own
(integration OVN-miassist-int-17, 2026-11-16: ``dict.update`` replaced a hand entry for the same
route and status, against the module's own rule)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import snapshot_shapes


def test_a_hand_entry_survives_a_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "responses.json"
    hand = {"schema": {"type": "object"}, "note": "hand-derived from cited code"}
    old = {"schema": {"type": "string"}, "generated": snapshot_shapes.GENERATED}
    target.write_text(
        json.dumps(
            {
                "about": "x",
                "apps": {
                    "midataworks": {
                        "commit": "abc1234",
                        "routes": {"GET /a": {"200": hand}, "GET /b": {"200": old}},
                    }
                },
            }
        )
    )
    monkeypatch.setattr(snapshot_shapes, "RESPONSES", target)
    new = {"schema": {"type": "integer"}, "generated": snapshot_shapes.GENERATED}
    snapshot_shapes.write(
        "midataworks", "abc1234", {"GET /a": {"200": new, "404": new}, "GET /b": {"200": new}}
    )
    routes = json.loads(target.read_text())["apps"]["midataworks"]["routes"]
    assert routes["GET /a"]["200"] == hand, "the hand entry was replaced"
    assert routes["GET /a"]["404"] == new
    assert routes["GET /b"]["200"] == new, "a generated entry is replaced on a re-run"
