"""Every sibling citation in ``src/miassist`` is classified, and miServer's are held to the pin
(2026-11-26; ``tests/support/source_citations.py``).

The source text is scanned, not a list: a code citation ``path.py:N`` (or ``N-M``), and a contract
pointer ``docs/schemas/<app>-answers-v1.json#/...``. Each code citation must be in ``CITED``; each
miServer one must be in ``MISERVER_LINES`` exactly as written (so a changed line number is a
reviewed change, re-checked against miServer by ``tests/cross_repo/test_miserver_citations_live.py``);
and a contract pointer resolves in the vendored copy when miAssist holds one. A citation split
across two lines would escape the scan, so it fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.support.source_citations import CITED, MISERVER_LINES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "miassist"
LINE = re.compile(r"(?<![\w/.-])((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.py):(\d+)(?:-(\d+))?")
POINTER = re.compile(r"docs/schemas/([a-z]+-answers-v1\.json)#(/[^\s`]+)")
WRAPPED = re.compile(r"\.py:\s*\n")


def scan() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """``(src file, cited path, as written)`` for each code citation; ``(src file, file, pointer)``
    for each contract pointer."""
    lines: list[tuple[str, str, str]] = []
    pointers: list[tuple[str, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        text, rel = path.read_text(), path.relative_to(SRC).as_posix()
        lines += [(rel, m.group(1), m.group(0)) for m in LINE.finditer(text)]
        pointers += [(rel, m.group(1), m.group(2)) for m in POINTER.finditer(text)]
    return lines, pointers


def test_the_scan_finds_both_kinds() -> None:
    lines, pointers = scan()
    assert len(lines) >= 30 and len(pointers) >= 4, (len(lines), len(pointers))


def test_every_code_citation_is_classified() -> None:
    lines, _ = scan()
    found = {(rel, cited) for rel, cited, _ in lines}
    assert not found - set(
        CITED
    ), f"classify in tests/support/source_citations.py: {found - set(CITED)}"
    assert not set(CITED) - found, f"stale CITED entries: {set(CITED) - found}"


def test_every_miserver_code_citation_is_pinned_as_written() -> None:
    lines, _ = scan()
    written = {w for rel, cited, w in lines if CITED[(rel, cited)] == "miserver"}
    assert written == set(MISERVER_LINES), (
        f"not in MISERVER_LINES: {written - set(MISERVER_LINES)}; "
        f"stale: {set(MISERVER_LINES) - written}"
    )


def test_no_citation_is_split_across_lines() -> None:
    split = [
        p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if WRAPPED.search(p.read_text())
    ]
    assert not split, f"write each citation on one line, so the scan reads it: {split}"


def resolve(doc: Any, pointer: str) -> Any:
    node = doc
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@pytest.mark.parametrize("pointer", sorted({p for _, _, p in scan()[1]}))
def test_a_contract_pointer_resolves_in_the_vendored_copy(pointer: str) -> None:
    files = {f for _, f, p in scan()[1] if p == pointer}
    for file in files:
        copy = ROOT / "docs" / "schemas" / file
        if not copy.is_file():
            pytest.skip(f"{file} is not vendored on this branch: the cross-repo test resolves it")
        assert resolve(json.loads(copy.read_text()), pointer) is not None
