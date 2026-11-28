"""FTDD §8 (memory leak-tests-must-look-for-the-encoded-form): a stub run's artifacts never hold the
client key's value or its base64 form."""

from __future__ import annotations

import base64
from pathlib import Path

from tests.support import suites

KEY = "sk-eval-test-key-0123456789abcdef"


async def test_no_artifact_holds_the_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    result = await suites.suite(tmp_path).run()
    assert result.records
    forms = [KEY.encode(), base64.b64encode(KEY.encode()), base64.urlsafe_b64encode(KEY.encode())]
    files = [p for p in result.out_dir.rglob("*") if p.is_file()]
    assert len(files) >= 5
    for path in files:
        data = path.read_bytes()
        assert not any(f in data for f in forms), path


def test_the_scan_would_find_it(tmp_path: Path) -> None:
    (tmp_path / "x").write_bytes(base64.b64encode(KEY.encode()))
    assert base64.b64encode(KEY.encode()) in (tmp_path / "x").read_bytes()
