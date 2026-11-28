"""R1 review fixes (OR1-002-2, OR1-002-7), 2026-11-16: the reviewer's leak probes, adopted.

No value the operator owns reaches the server under test, the effects log, a take or the allowed
set: the recorder never grows the allowed set from an answer (OVN-miassist-eval-20, reversing
OVN-7), filters every list (parameterised GETs included), refuses an answer still carrying a
non-fixture value (``foreign_id``) or text (``text_answer_refused``), and ``write_take`` is the one
choke point (Core's ``final_scan`` over the scan view, then the secret scan).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from miassist_eval import allowed, cassette, classes, secret_scan
from miassist_eval.classes import Refusal
from miassist_eval.recorder import Recorder
from tests.support import harness

HW = harness.HEADERS["miworkbench"]
HD = harness.HEADERS["midataworks"]
OPERATOR = "operator-feat-991"


def rec_with(answer: Any) -> Recorder:
    async def forward(app, method, path, query, headers, body):
        return 200, {}, answer

    return Recorder(
        edge=harness.edge(),
        forward=forward,
        allowed_set=allowed.AllowedSet(),
        app_versions={"miworkbench": "t", "midataworks": "t"},
        writing=True,
    )


def everything(rec: Recorder, seen: Any) -> str:
    """Every place a value could land: what the server under test got, the effects log, the take
    (if one is writable) and the allowed set."""
    try:
        take = json.dumps(rec.cassette("t"))
    except Refusal:
        take = ""
    return json.dumps([seen, rec.effects.lines, take, sorted(rec.allowed_set.created)], default=str)


async def test_related_features_under_a_fixture_parent_are_filtered_not_admitted() -> None:
    """The reviewer's P1: ``GET /features/evalfx-f1/related`` holding an operator feature. Before
    the fix the take was WRITTEN with ``operator-feat-991`` and its name in it."""
    rec = rec_with({"related": [{"feature_id": OPERATOR, "name": "customer-churn-feature"}]})
    status, _, seen = await rec.handle(
        "miworkbench", "GET", "/api/v1/features/evalfx-f1/related", {}, HW, None
    )
    assert status == 200 and seen == {"related": []}
    text = everything(rec, seen)
    assert OPERATOR not in text and "customer-churn-feature" not in text
    assert not rec.allowed_set.allows(OPERATOR)


async def test_a_foreign_id_left_after_the_filter_is_refused_and_never_admitted() -> None:
    rec = rec_with({"feature_id": "evalfx-f1", "parent_feature_id": OPERATOR})
    status, _, seen = await rec.handle(
        "miworkbench", "GET", "/api/v1/features/evalfx-f1", {}, HW, None
    )
    assert status == 502 and seen["refused"] == classes.FOREIGN_ID
    assert OPERATOR not in everything(rec, seen)
    assert rec.records == [] and [c for c, _ in rec.failures] == [classes.FOREIGN_ID]


def b64(obj: Any) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


#: Forms 002's scan view now expands (JSON and base64 embedded at any offset) or refuses (text).
REFUSED = [
    (
        "json-in-string",
        {"id": "evalfx-ds-1", "detail": json.dumps({"dataset_id": "operator-ds-7"})},
    ),
    (
        "json-at-an-offset",
        {"id": "evalfx-ds-1", "detail": 'failed: {"dataset_id": "operator-ds-7"} (see log)'},
    ),
    ("b64-in-string", {"id": "evalfx-ds-1", "blob": b64({"dataset_id": "operator-ds-7"})}),
    (
        "b64-at-an-offset",
        {"id": "evalfx-ds-1", "blob": "abc" + b64({"dataset_id": "operator-ds-7"})},
    ),
    (
        "b64url-in-a-list",
        {
            "id": "evalfx-ds-1",
            "notes": [base64.urlsafe_b64encode(b'[{"model_id": "op-m-1"}]').decode()],
        },
    ),
]


@pytest.mark.parametrize(("label", "answer"), REFUSED, ids=[r[0] for r in REFUSED])
async def test_an_embedded_foreign_id_is_refused(label: str, answer: Any) -> None:
    rec = rec_with(answer)
    status, _, seen = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, HD, None
    )
    assert status == 502 and seen["refused"] == classes.FOREIGN_ID, label
    assert "operator-ds-7" not in everything(rec, seen) and "op-m-1" not in everything(rec, seen)


async def test_a_text_answer_is_refused() -> None:
    rec = rec_with("operator-ds-7,operator-ds-8")
    status, _, seen = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, HD, None
    )
    assert status == 502 and seen["refused"] == classes.TEXT_ANSWER_REFUSED
    assert "operator-ds-7" not in everything(rec, seen)


#: Forms Core's rule does not see yet (identifying field names, plurals, dict keys): Core's fixer
#: owns ``miassist_fixtures/filter.py`` (NEEDS item 5). Strict: each turns red once Core's rule
#: catches it, so the marker is removed at the integration rebase.
CORE_OWNED = [
    ("ids-plural-field", {"id": "evalfx-ds-1", "ids": ["operator-ds-7"]}),
    ("non-id-field", {"id": "evalfx-ds-1", "source": "operator-ds-7", "parent": "operator-ds-9"}),
    ("dict-keyed", {"id": "evalfx-ds-1", "by_id": {"operator-ds-7": {"rows": 3}}}),
]


@pytest.mark.xfail(strict=True, reason="Core's rule (NEEDS 5): field names, ids, dict keys")
@pytest.mark.parametrize(("label", "answer"), CORE_OWNED, ids=[r[0] for r in CORE_OWNED])
async def test_core_owned_forms_are_refused(label: str, answer: Any) -> None:
    rec = rec_with(answer)
    status, _, seen = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, HD, None
    )
    assert status == 502 and seen["refused"] == classes.FOREIGN_ID, label


# ------------------------------------------------------------------ write_take, the choke point
def manifest() -> dict[str, Any]:
    return {
        "cassette_id": "goal-miassist-t1",
        "goal_id": "goal",
        "surface": "miassist",
        "take": "t1",
        "recording_run_id": "run-1",
        "recorder_version": "0.1.0",
        "started_utc": "2026-11-16T09:00:00+00:00",
        "ended_utc": "2026-11-16T09:10:00+00:00",
        "apps": {"midataworks": {"base_path": "", "openapi_sha256": "x", "version": "test"}},
        "fairness": harness.fairness_block(),
        "allowed_ids": [],
    }


def take_with(body: Any) -> dict[str, Any]:
    rec = harness.record(
        0,
        "midataworks",
        "GET",
        "/api/v1/datasets/evalfx-ds-1",
        "/api/v1/datasets/{dataset_id}",
        200,
        body,
    )
    return harness.cassette_doc([rec])


def write(tmp_path: Path, body: Any, **kw: Any) -> Path:
    return cassette.write_take(
        tmp_path / "t1", take_with(body), manifest(), {"run_id": "run-1"}, {}, {}, **kw
    )


def test_write_take_refuses_a_stray_id_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        write(
            tmp_path, {"id": "evalfx-ds-1", "detail": json.dumps({"dataset_id": "operator-ds-7"})}
        )
    assert caught.value.cls == classes.FIXTURE_NOT_ALLOWED
    assert not (tmp_path / "t1").exists()


def test_write_take_allows_only_fixture_data_by_default(tmp_path: Path) -> None:
    with pytest.raises(Refusal):
        write(tmp_path, {"id": "ds-made-by-the-run"})
    run_set = allowed.fixture_set()
    run_set.created.add("ds-made-by-the-run")  # only a caller passing its own set may widen it
    assert write(tmp_path, {"id": "ds-made-by-the-run"}, allowed_set=run_set).is_dir()


@pytest.mark.parametrize(
    "where",
    ["raw", "base64-at-an-offset", "base64url", "json-escaped"],
)
def test_write_take_refuses_a_secret_and_writes_nothing(tmp_path: Path, where: str) -> None:
    key = "sk-ant-api03-" + "A" * 10 + "_-_-" + "B" * 30
    fresh = "fresh-run-key-0123456789abcdef"
    payload = json.dumps({"k": key}).encode()
    body = {
        "raw": {"id": "evalfx-ds-1", "note": key},
        "base64-at-an-offset": {
            "id": "evalfx-ds-1",
            "note": "abc" + base64.b64encode(payload).decode(),
        },
        "base64url": {
            "id": "evalfx-ds-1",
            "note": base64.urlsafe_b64encode(fresh.encode()).decode(),
        },
        "json-escaped": {"id": "evalfx-ds-1", "note": key.replace("-", "\\u002d")},
    }[where]
    with pytest.raises(Refusal) as caught:
        write(tmp_path, body, listed=[fresh])
    assert caught.value.cls == classes.SECRET_IN_TAKE, where
    assert not (tmp_path / "t1").exists()


def test_the_secret_scan_tries_every_alignment_and_undoes_escapes() -> None:
    """The reviewer's P3 misses, now found."""
    shaped = "sk-ant-api03-" + "A" * 10 + "_-_-" + "B" * 30
    payload = json.dumps({"k": shaped, "pad": "??>>??>>"}).encode()
    assert secret_scan.scan_bytes(("abc" + base64.b64encode(payload).decode()).encode())
    escaped = json.dumps({"k": shaped}).replace("-", "\\u002d").encode()
    assert secret_scan.scan_bytes(escaped)
