"""``scripts.snapshot_shapes.write`` keeps a hand-derived entry (003's) and replaces only its own
(integration OVN-miassist-int-17, 2026-11-16: ``dict.update`` replaced a hand entry for the same
route and status, against the module's own rule)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def test_a_non_ascii_value_round_trips_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-11-26: ``write`` keeps a non-ASCII character as itself, as the committed file does;
    it used to rewrite it as an escape, so a re-run changed bytes it had no reason to touch."""
    target = tmp_path / "responses.json"
    hand = {"schema": {"type": "object"}, "note": "naïve – “quoted” → kept"}
    before: dict[str, Any] = {
        "about": "x",
        "apps": {"midataworks": {"commit": "abc1234", "routes": {"GET /a": {"200": hand}}}},
    }
    target.write_text(snapshot_shapes.render(before), encoding="utf-8")
    monkeypatch.setattr(snapshot_shapes, "RESPONSES", target)
    snapshot_shapes.write("midataworks", "abc1234", {})
    raw = target.read_text(encoding="utf-8")
    assert "naïve – “quoted” → kept" in raw and "\\u" not in raw
    assert raw == snapshot_shapes.render(before), "a re-run with nothing new changes no byte"


def test_the_committed_file_is_in_the_writers_form() -> None:
    """The committed ``responses.json`` is exactly what ``render`` writes, so the generator and
    the file agree on every byte they share."""
    raw = snapshot_shapes.RESPONSES.read_text(encoding="utf-8")
    assert raw == snapshot_shapes.render(json.loads(raw))


def test_render_sorts_keys_at_every_level() -> None:
    """``render`` sorts keys itself: the committed file's order is not an accident of how the dict
    was built (006-1 review, R3: ``sort_keys=False`` survived, since every other test renders a
    dict loaded from an already sorted file)."""
    assert snapshot_shapes.render({"b": 1, "a": {"d": [{"z": 0, "y": 1}], "c": "λ"}}) == (
        '{\n "a": {\n  "c": "λ",\n  "d": [\n   {\n    "y": 1,\n    "z": 0\n   }\n  ]\n },\n "b": 1\n}\n'
    )
