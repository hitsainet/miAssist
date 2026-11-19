"""Every file under ``docs/schemas/`` is owned and in sync (PADR ADR-008; Foundation task 1.4).

Scanned, not listed: each file found must have an ``OWNERSHIP`` entry. ``MIASSIST_SCHEMAS_DIR``
points the scan at another directory (the negative control drops an unowned ``x.json`` into a temp
copy). Owned files are regenerated and byte-compared; vendored files are byte-compared with the
owner's copy.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.contract.schema_ownership import NOT_SCHEMAS, OWNERSHIP, Owned, Vendored
from tests.support import siblings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "docs" / "schemas"


def schemas_dir() -> Path:
    override = os.environ.get("MIASSIST_SCHEMAS_DIR")
    return Path(override) if override else DEFAULT_DIR


def scanned() -> list[str]:
    return sorted(
        p.name for p in schemas_dir().iterdir() if p.is_file() and p.name not in NOT_SCHEMAS
    )


def test_readme_exists() -> None:
    assert (schemas_dir() / "README.md").is_file()


def test_every_file_is_owned() -> None:
    unowned = [name for name in scanned() if name not in OWNERSHIP]
    assert not unowned, f"docs/schemas/ holds files no one owns: {unowned} (add OWNERSHIP entries)"


def test_every_owned_entry_exists() -> None:
    missing = [name for name in OWNERSHIP if not (schemas_dir() / name).is_file()]
    assert not missing, f"OWNERSHIP names files that are not in docs/schemas/: {missing}"


def _readme_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in (schemas_dir() / "README.md").read_text().splitlines():
        match = re.match(r"^\|\s*`([^`]+)`\s*\|\s*(owned|vendored)\b", line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def test_readme_table_matches_ownership() -> None:
    expected = {
        name: "owned" if isinstance(entry, Owned) else "vendored"
        for name, entry in OWNERSHIP.items()
    }
    assert _readme_rows() == expected


@pytest.mark.parametrize(
    "name", [n for n, e in OWNERSHIP.items() if isinstance(e, Owned)] or ["(none yet)"]
)
def test_owned_file_regenerates_identically(name: str) -> None:
    if name == "(none yet)":
        pytest.skip("no owned schema yet (feature 001 adds them)")
    from scripts.write_contracts import render

    entry = OWNERSHIP[name]
    assert isinstance(entry, Owned)
    assert (
        render(entry.name) == (schemas_dir() / name).read_bytes()
    ), f"{name} differs from what scripts/write_contracts.py generates; regenerate, never hand-edit"


@pytest.mark.parametrize(
    "name", [n for n, e in OWNERSHIP.items() if isinstance(e, Vendored)] or ["(none yet)"]
)
def test_vendored_file_is_byte_identical(name: str) -> None:
    if name == "(none yet)":
        pytest.skip("no vendored schema yet (feature 001 adds them)")
    entry = OWNERSHIP[name]
    assert isinstance(entry, Vendored)
    root = siblings.require_root(entry.sibling, f"{name} cannot be compared with its owner's copy")
    source = root / entry.path
    if not source.is_file():
        siblings.absent(f"{entry.sibling.name} has no {entry.path}; {name} cannot be compared")
    assert (
        source.read_bytes() == (schemas_dir() / name).read_bytes()
    ), f"{name} is not byte-identical to {entry.sibling.name}/{entry.path}; re-vendor it"
