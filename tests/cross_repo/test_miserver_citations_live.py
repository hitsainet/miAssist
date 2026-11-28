"""Every miServer citation in ``src/miassist`` says what it claims at miAssist's miServer pin
(2026-11-26; ``tests/support/source_citations.py``).

Read from miServer's own repository at the commit ``tests/fixtures/openapi/miserver.json`` pins
(``git show <commit>:<file>``; nothing is written in the sibling):
- each code citation's lines exist, and its anchor text is inside them;
- each contract pointer resolves in ``docs/schemas/miserver-answers-v1.json`` at that commit.

Skips loudly when miServer is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1`` or
``MISTUDIO_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache

import pytest

from tests.contract.test_source_citations import resolve, scan
from tests.support import response_shapes as rs
from tests.support import siblings
from tests.support.source_citations import MISERVER_LINES

pytestmark = pytest.mark.cross_repo
RANGE = re.compile(r":(\d+)(?:-(\d+))?$")


@cache
def shown(path: str) -> str:
    root = siblings.require_root(siblings.MISERVER, "miServer citations cannot be checked")
    commit = str(rs.snapshot("miserver")["commit"])
    done = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"miServer has no {path} at {commit}"
    return done.stdout


@pytest.mark.parametrize("written", sorted(MISERVER_LINES))
def test_each_code_citation_holds_its_anchor(written: str) -> None:
    path, anchor = MISERVER_LINES[written]
    found = RANGE.search(written)
    assert found, written
    first = int(found.group(1))
    last = int(found.group(2) or first)
    lines = shown(path).splitlines()
    assert last <= len(lines), f"{written}: {path} has {len(lines)} lines"
    cited = "\n".join(lines[first - 1 : last])
    assert anchor in cited, (
        f"{written}: {anchor!r} is not in lines {first}-{last} of miServer's {path} at "
        f"{rs.snapshot('miserver')['commit']}; re-pin the citation"
    )


@pytest.mark.parametrize(
    "pointer", sorted({p for _, f, p in scan()[1] if f == "miserver-answers-v1.json"})
)
def test_each_contract_pointer_resolves_in_miservers_contract(pointer: str) -> None:
    contract = json.loads(shown("docs/schemas/miserver-answers-v1.json"))
    assert resolve(contract, pointer) is not None
