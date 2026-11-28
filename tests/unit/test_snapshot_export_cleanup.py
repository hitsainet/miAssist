"""``scripts.snapshot_openapi.export`` removes its temporary tree when the process exits.

Every cross-repo run and every re-pin exports each sibling with ``git archive`` into a temporary
directory; nothing removed them, and by the 018 re-pin (2026-11-19) about 1,370 trees (some 56 GB)
had piled up under /tmp. The export is made in a child process (miAssist's own committed ``HEAD``,
so no sibling is needed), which prints the path and exits; the tree must be gone afterwards.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CHILD = """
import sys
from pathlib import Path
from scripts import snapshot_openapi as snap
tree, sha = snap.export("miAssist", "HEAD", repo=Path(sys.argv[1]))
assert (tree / "pyproject.toml").is_file(), tree
print(tree)
"""


def test_the_exported_tree_is_removed_at_exit() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(REPO)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    tree = Path(result.stdout.strip().splitlines()[-1])
    assert tree.name.startswith("snapshot-miAssist-"), tree
    assert not tree.exists(), f"{tree} was left behind"
