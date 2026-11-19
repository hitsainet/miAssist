"""The vendored per-route payload vectors are byte-identical to miWorkbench 045's (001 FTASKS 5.2a;
A29, R1A-8). Skips loudly when miWorkbench is absent or has not published the file; fails under
``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1`` or ``MISTUDIO_REQUIRE_CROSS_REPO_CHECKS=1``."""

from __future__ import annotations

import subprocess

import pytest

from tests.support import siblings
from tests.support.vectors import VECTORS_FILE

pytestmark = pytest.mark.cross_repo
PUBLISHED = "docs/schemas/miworkbench-approval-payload-vectors-v1.json"


def committed(root: object, ref: str = "HEAD") -> bytes | None:
    """The file at the sibling's committed ``ref``, never its working tree (OVN-miassist-core-12;
    R1 seam: an uncommitted edit in the owner's worktree must not decide this test)."""
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{PUBLISHED}"], capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def test_bytes() -> None:
    root = siblings.require_root(siblings.MIWORKBENCH, "the payload vectors cannot be compared")
    source = committed(root)
    if source is None:
        siblings.absent(f"miWorkbench at {root} has no committed {PUBLISHED} (045-A0 not there)")
    assert source == VECTORS_FILE.read_bytes(), "re-vendor the vectors byte for byte"
