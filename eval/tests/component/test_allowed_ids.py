"""FR-002.14b: the recorder refuses a non-fixture id BEFORE the app sees it; an id an answer carries
is never admitted (R1 review fix OR1-002-2, OVN-miassist-eval-20 reversing OVN-7); the last pass
refuses a take holding a stray id."""

from __future__ import annotations

import pytest

from miassist_eval import allowed, classes
from miassist_eval.classes import Refusal
from miassist_eval.recorder import Recorder
from tests.support import harness

H = harness.HEADERS["midataworks"]


class StubApp:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    async def __call__(self, app, method, path, query, headers, body):
        self.log.append((method, path))
        if method == "POST" and path == "/api/v1/datasets":
            return 201, {}, {"id": "ds-new-1", "name": body.get("name")}
        if method == "GET" and path.startswith("/api/v1/datasets/"):
            return 200, {}, {"id": path.rsplit("/", 1)[1], "name": "evalfx-x", "version_list": []}
        return 200, {}, {}


def recorder(stub: StubApp, writing: bool = True) -> Recorder:
    return Recorder(
        edge=harness.edge(),
        forward=stub,
        allowed_set=allowed.AllowedSet(),
        app_versions={"midataworks": "t"},
        writing=writing,
    )


async def test_a_foreign_id_never_reaches_the_app() -> None:
    stub = StubApp()
    rec = recorder(stub)
    status, _, body = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/ds-operator-9", {}, H, None
    )
    assert status == 403 and body == {"refused": "fixture_not_allowed", "at": "path.dataset_id"}
    assert stub.log == [], "the stub app saw the refused request"
    assert rec.records == []
    assert rec.failures[0][0] == classes.FIXTURE_NOT_ALLOWED


async def test_a_server_assigned_id_is_never_admitted() -> None:
    """R1 review fix (OR1-002-2): the run's create answers a server-assigned id. The answer is
    refused (``foreign_id``), not recorded, not passed on, and the id is never added: a later read
    by it is refused before the app sees it."""
    stub = StubApp()
    rec = recorder(stub)
    status, _, body = await rec.handle(
        "midataworks", "POST", "/api/v1/datasets", {}, H, {"name": "evalfx-refund-set"}
    )
    assert status == 502 and body["refused"] == classes.FOREIGN_ID
    assert "ds-new-1" not in str(body) and "ds-new-1" not in str(rec.effects.lines)
    assert not rec.allowed_set.allows("ds-new-1")
    status, _, _ = await rec.handle("midataworks", "GET", "/api/v1/datasets/ds-new-1", {}, H, None)
    assert status == 403
    assert stub.log == [("POST", "/api/v1/datasets")]
    assert rec.records == []
    assert [c for c, _ in rec.failures] == [classes.FOREIGN_ID, classes.FIXTURE_NOT_ALLOWED]


async def test_a_fixture_id_passes() -> None:
    stub = StubApp()
    rec = recorder(stub)
    status, _, _ = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, H, None
    )
    assert status == 200 and stub.log == [("GET", "/api/v1/datasets/evalfx-ds-1")]


async def test_the_last_pass_refuses_a_stray_id() -> None:
    rec = recorder(StubApp())
    await rec.handle("midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, H, None)
    rec.records[0]["answer"]["body"]["dataset_id"] = "prod-7"  # a stray id that slipped in
    with pytest.raises(Refusal) as caught:
        rec.cassette("t")
    assert caught.value.cls == classes.FIXTURE_NOT_ALLOWED


async def test_a_clean_take_is_written_in_cores_format() -> None:
    from miassist_eval import schemas

    rec = recorder(StubApp())
    await rec.handle("midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, H, None)
    doc = rec.cassette("t")
    assert schemas.cassette_errors(doc) == []
    assert doc["records"][0]["request"]["headers"] == {"X-Dataworks-Agent": "agent:miassist"}


async def test_gap_recording_refuses_any_method_but_get() -> None:
    from miassist_eval.classes import Refusal

    stub = StubApp()
    rec = recorder(stub)
    rec.gap_only = True
    with pytest.raises(Refusal):
        await rec.handle("midataworks", "POST", "/api/v1/datasets", {}, H, {"name": "evalfx-x"})
    assert stub.log == []
    status, _, _ = await rec.handle(
        "midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, H, None
    )
    assert status == 200


async def test_credentials_are_stripped_before_forwarding() -> None:
    seen = []

    async def forward(app, method, path, query, headers, body):
        seen.append(dict(headers))
        return 200, {}, {"id": "evalfx-ds-1"}

    rec = Recorder(
        edge=harness.edge(),
        forward=forward,
        allowed_set=allowed.AllowedSet(),
        app_versions={},
        writing=True,
    )
    await rec.handle(
        "midataworks",
        "GET",
        "/api/v1/datasets/evalfx-ds-1",
        {},
        {**H, "Authorization": "Bearer x", "Cookie": "c", "X-Api-Key": "k"},
        None,
    )
    assert {k.lower() for k in seen[0]} == {"x-dataworks-agent"}
