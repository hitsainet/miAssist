"""FR-002.13: one byte, a re-hashed manifest, an edited index entry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist_eval import cassette, classes
from miassist_eval.canonical import sha256_file
from miassist_eval.classes import Refusal
from tests.support import harness


def take(tmp_path: Path) -> cassette.Take:
    rec = harness.record(
        0,
        "midataworks",
        "GET",
        "/api/v1/datasets/evalfx-ds-1",
        "/api/v1/datasets/{dataset_id}",
        200,
        {"id": "evalfx-ds-1"},
    )
    return harness.write_take(tmp_path, [rec])


def refuse(tmp_path: Path, t: cassette.Take) -> str:
    with pytest.raises(Refusal) as caught:
        cassette.load(t.path, cassette.read_index(tmp_path))
    assert caught.value.cls == classes.CASSETTE_INTEGRITY
    return caught.value.detail


def test_a_clean_take_loads(tmp_path: Path) -> None:
    t = take(tmp_path)
    assert cassette.load(t.path, cassette.read_index(tmp_path)).cassette["records"]


def test_one_byte_in_a_recorded_answer_refuses_naming_the_file(tmp_path: Path) -> None:
    t = take(tmp_path)
    path = t.path / "cassette.json"
    path.write_text(path.read_text().replace("evalfx-ds-1", "evalfx-ds-2", 1))
    assert "cassette.json" in refuse(tmp_path, t)


def test_a_rehashed_manifest_refuses_on_the_index(tmp_path: Path) -> None:
    t = take(tmp_path)
    path = t.path / "cassette.json"
    path.write_text(path.read_text().replace("evalfx-ds-1", "evalfx-ds-2", 1))
    manifest = json.loads((t.path / "MANIFEST.json").read_text())
    manifest["files"]["cassette.json"] = sha256_file(path)
    (t.path / "MANIFEST.json").write_text(json.dumps(manifest))
    assert "INDEX.json" in refuse(tmp_path, t)


def test_a_missing_recording_run_record_refuses(tmp_path: Path) -> None:
    t = take(tmp_path)
    (t.path / "recording" / "run.json").unlink()
    assert "missing" in refuse(tmp_path, t)


def test_an_unlisted_extra_file_refuses(tmp_path: Path) -> None:
    t = take(tmp_path)
    (t.path / "extra.json").write_text("{}")
    assert "not in MANIFEST" in refuse(tmp_path, t)


def test_an_unindexed_take_refuses(tmp_path: Path) -> None:
    t = take(tmp_path)
    (tmp_path / "INDEX.json").write_text("[]")
    assert "not in INDEX" in refuse(tmp_path, t)


def test_the_index_is_append_only() -> None:
    old = [{"cassette_id": "a", "manifest_sha256": "1", "recording_run_id": "r", "added_utc": "t"}]
    assert cassette.index_changes(old, old + [{**old[0], "cassette_id": "b"}]) == []
    assert cassette.index_changes(old, [{**old[0], "retired_utc": "t2", "reason": "stale"}]) == []
    assert cassette.index_changes(old, [{**old[0], "manifest_sha256": "2"}]) == [
        "a: manifest_sha256 changed"
    ]
    assert cassette.index_changes(old, []) == ["a: removed from the index"]


def test_the_committed_index_only_grew(cassette_root: Path) -> None:
    """Against the previous committed INDEX.json (git), when there is one."""
    import subprocess

    rel = cassette_root.relative_to(cassette_root.parents[4]) / "INDEX.json"
    prev = subprocess.run(
        ["git", "show", f"HEAD~1:{rel}"],
        cwd=cassette_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if prev.returncode != 0:
        pytest.skip("LOUD SKIP: no previous committed INDEX.json")
    current = cassette.read_index(cassette_root)
    assert cassette.index_changes(json.loads(prev.stdout), current) == []
