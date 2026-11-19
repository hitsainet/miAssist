"""FR-002.14 (R1M-5; FTID §3.18): build the stripped tree from Foundation's strip list (parsed from
sync-to-clean.yml), after planting a cassette, and find no cassette anywhere.

R1 review fix (OR1-002-8), 2026-11-16: 002 no longer edits the strip (OVN-miassist-eval-15 is
superseded); Foundation's ``.github/scripts/cassette_strip.py`` (001 @ 865ba70, OR1-001-3) covers the
draft and escaped shapes. On this branch's base that script is absent, so those two shapes are
checked only when the strip calls it (they become strict by themselves at the rebase onto 001,
OR1-002-3); the v1 cassette under the root is checked always. This file must itself survive the
strip: its literals are built from parts so no matcher reads it as a cassette."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
FORMAT = "miassist.cassette/v1"
PLANTED = "tests/fixtures/cassettes/private/eval/detector-refund/baseline/t1/cassette.json"
#: Two shapes the strip's original rules missed (C-19's first run survived; OVN-miassist-eval-15):
#: a draft's own cassette format under a `cassettes` directory (the path a playbook draft used), and
#: a v1 cassette written with a JSON-escaped slash outside any cassette directory.
PLANTED_DRAFT = "tests/cassettes/detector-probe/x.json"
DRAFT = '{"interactions": [{"request": {}, "response": {}}]}'
PLANTED_ESCAPED = "tests/fixtures/draft_recording.json"
ESCAPED = (
    '{"format": "miassist.cassette'
    + "\\"
    + '/v1", "name": "x", "source": "recorded", "records": []}'
)


def strip_script() -> str:
    doc = yaml.safe_load((REPO / ".github/workflows/sync-to-clean.yml").read_text())
    step = next(
        s
        for s in doc["jobs"]["sync"]["steps"]
        if s.get("name") == "Remove excluded files and folders"
    )
    return str(step["run"])


def tracked_copy(dest: Path) -> None:
    """The tree the mirror would get: tracked files only (eval/runs/ is git-ignored)."""
    files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout
    for rel in filter(None, files.decode().split("\0")):
        src = REPO / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)


def cassettes_in(root: Path) -> list[str]:
    found = []
    for p in root.rglob("*"):
        rel = str(p.relative_to(root))
        if p.is_dir() and p.name == "cassettes":
            found.append(f"dir {rel}")
        elif p.is_file() and p.suffix == ".json":
            try:
                if json.loads(p.read_text()).get("format") == FORMAT:
                    found.append(f"file {rel}")
            except (ValueError, AttributeError, UnicodeDecodeError):
                pass
    for banned in ("tests/fixtures/cassettes/private", "0xcc", "eval/runs"):
        if (root / banned).exists():
            found.append(f"path {banned}")
    return found


def prune_empty_dirs(root: Path) -> None:
    for p in sorted(
        (d for d in root.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True
    ):
        if not any(p.iterdir()):
            p.rmdir()


def plant(root: Path, rel: str = PLANTED) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(
        json.dumps({"format": FORMAT, "name": "x", "source": "recorded", "records": []})
    )


def plant_draft(root: Path) -> None:
    for rel, text in ((PLANTED_DRAFT, DRAFT), (PLANTED_ESCAPED, ESCAPED)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def foundation_matcher() -> bool:
    return "cassette_strip.py" in strip_script()


def test_the_unstripped_tree_holds_the_planted_cassettes(tmp_path: Path) -> None:
    tracked_copy(tmp_path)
    plant(tmp_path)
    plant_draft(tmp_path)
    found = cassettes_in(tmp_path)
    assert f"file {PLANTED}" in found and f"file {PLANTED_ESCAPED}" in found
    assert "dir tests/cassettes" in found


def test_the_stripped_tree_holds_no_cassette_anywhere(tmp_path: Path) -> None:
    """Integration (OVN-miassist-int-4), 2026-11-16: on 001's settled stack Foundation's strip is
    FAIL-CLOSED (OVN-miassist-core-31). A cassette under a ``cassettes`` directory (the v1 root, the
    draft's directory) is removed and the publish goes on; the escaped-slash file outside any
    cassette directory is REFUSED by name, so nothing is published (next test)."""
    assert foundation_matcher(), "the strip no longer calls Foundation's cassette_strip.py"
    tracked_copy(tmp_path)
    plant(tmp_path)
    (tmp_path / PLANTED_DRAFT).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / PLANTED_DRAFT).write_text(DRAFT)
    (tmp_path / "eval/runs/s-1").mkdir(parents=True)
    result = subprocess.run(
        ["bash", "-c", strip_script()], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    shutil.rmtree(tmp_path / "eval/runs")  # git-ignored: never in a commit, so never on the mirror
    prune_empty_dirs(tmp_path)  # git publishes files, never an empty directory
    assert cassettes_in(tmp_path) == []
    assert (tmp_path / "eval/miassist_eval/__init__.py").is_file(), "the harness code was stripped"
    assert (tmp_path / "eval/tests/unit/test_mirror_strip.py").is_file(), "this test was stripped"


def test_an_escaped_cassette_outside_a_cassette_directory_refuses_the_publish(
    tmp_path: Path,
) -> None:
    """The escaped-slash v1 file C-19 found is never published: the fail-closed strip stops the job
    (non-zero exit, ``set -e``) and names the file (integration OVN-miassist-int-4)."""
    tracked_copy(tmp_path)
    plant_draft(tmp_path)
    result = subprocess.run(
        ["bash", "-c", strip_script()], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0, "a cassette outside a cassette directory was published"
    assert f"REFUSED - {PLANTED_ESCAPED}" in result.stdout + result.stderr


def test_this_file_is_not_a_cassette_to_any_matcher() -> None:
    """Foundation's content matcher deleted this file from the mirror (its ESCAPED literal read as a
    v1 declaration). The literal is built from parts now; check with Foundation's own normalisation
    rules: JSON escapes undone and whitespace removed."""
    import re

    text = Path(__file__).read_text()
    for _ in range(2):
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        text = text.replace("\\/", "/").replace('\\"', '"')
    text = re.sub(r"\s+", "", text)
    declares = re.compile(r"""["']?format["']?:["']?miassist\.cassette/v1""", re.IGNORECASE)
    assert not declares.search(text)
