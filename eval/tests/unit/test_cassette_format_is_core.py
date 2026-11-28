"""FR-002.10 (A22, R1M-5): every take's cassette, and the recorder's output on a stub, validates
against Core's schema FILE (not a copy); no record keeps a header outside the allow-list."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from miassist_eval import allowed, cassette, classes, schemas
from miassist_eval.classes import Refusal
from miassist_eval.recorder import Recorder
from tests.support import harness


def core_schema_present() -> None:
    path = schemas.core_cassette_schema_path()
    if not path.is_file():
        if os.environ.get("MIASSIST_REQUIRE_CORE") == "1":
            pytest.fail(f"Core's cassette schema {path} is absent")
        pytest.skip(f"LOUD SKIP: Core's cassette schema {path} is absent (push 001-A)")


def test_the_schema_is_cores_file_not_a_copy() -> None:
    core_schema_present()
    assert schemas.core_cassette_schema_path().resolve() == (
        Path(__file__).resolve().parents[3] / "tests/fixtures/miassist-cassette-v1.schema.json"
    )
    assert not list((schemas.SCHEMA_DIR).glob("*cassette*")), "a cassette schema of 002's own"


async def test_the_recorders_output_validates_and_keeps_only_allowed_headers() -> None:
    core_schema_present()

    async def forward(app, method, path, query, headers, body):
        return (
            200,
            {"X-MiStudio-Approval": "pending", "Set-Cookie": "s=1", "X-Secret": "k"},
            {"id": "evalfx-ds-1"},
        )

    rec = Recorder(
        edge=harness.edge(),
        forward=forward,
        allowed_set=allowed.AllowedSet(),
        app_versions={"midataworks": "t"},
        writing=True,
    )
    headers = {**harness.HEADERS["midataworks"], "Authorization": "Bearer x", "Cookie": "c=1"}
    await rec.handle("midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, headers, None)
    doc = rec.cassette("t")
    assert schemas.cassette_errors(doc) == []
    record = doc["records"][0]
    assert record["request"]["headers"] == {"X-Dataworks-Agent": "agent:miassist"}
    assert record["answer"]["headers"] == {"X-MiStudio-Approval": "pending"}
    assert record["request"]["body"] is None and "body" in record["request"]


def test_a_missing_schema_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIASSIST_CORE_CASSETTE_SCHEMA", str(tmp_path / "absent.json"))
    with pytest.raises(Refusal) as caught:
        schemas.core_cassette_schema()
    assert caught.value.cls == classes.CASSETTE_SCHEMA_MISSING


def test_a_body_outside_request_body_is_refused() -> None:
    core_schema_present()
    rec = harness.record(0, "midataworks", "GET", "/api/health", "/api/health", 200, {})
    rec["body"] = rec["request"].pop("body")
    assert schemas.cassette_errors(harness.cassette_doc([rec]))


def test_every_committed_take_validates(cassette_root: Path) -> None:
    core_schema_present()
    for take in cassette.find_takes(cassette_root):
        doc = json.loads((take / "cassette.json").read_text())
        assert schemas.cassette_errors(doc) == [], take
        for r in doc["records"]:
            assert {h.lower() for h in r["request"].get("headers", {})} <= cassette.REQUEST_HEADERS
            assert {h.lower() for h in r["answer"].get("headers", {})} <= cassette.ANSWER_HEADERS
