"""Every miServer hint name maps (001 FTASKS 4.6)."""

from __future__ import annotations

import json
from pathlib import Path

from miassist.results.miserver_hints import load_hints, next_from_hint

VENDORED = Path(__file__).resolve().parents[2] / "docs/schemas/next-tool-hints.json"


def test_every_hint_mapped() -> None:
    names = json.loads(VENDORED.read_text())["next_tools"]
    hints = load_hints()
    assert len(names) == 15
    assert set(names) <= set(hints)
    for name in names:
        mapped = next_from_hint(name, hints)
        assert mapped, name
        if isinstance(mapped, dict):
            assert mapped["tool"].startswith("miassist_")
        else:
            assert "miserver_" not in mapped
