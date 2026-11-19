"""miAssist never exposes a miDataworks source imported with a credential (OVN-miassist-core-32;
miDataworks review OR3-022-1, 2026-11-16).

Every path, each with its control (the same call over a source imported with no credential):
the source list, one source, its rows, its preview (profile), a build or version input, an id in a
list field, an answer embedding a source record, and the fail-closed cases (tier missing, null or
unknown; the source unreadable). A refused call never reaches the app's route.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from miassist.adapters.midataworks import GET_SOURCE, showable
from miassist.adapters.routes import ROUTES
from miassist.errors import MiAssistError
from tests.support.clients import client_for, no_pending, test_registry
from tests.support.fake_apps import FakeApp

OPEN = {"id": "src-open", "display_name": "evalfx-public", "token_tier": "none", "gated": None}
STORED = {"id": "src-stored", "display_name": "private", "token_tier": "stored", "gated": None}
PER_IMPORT = {"id": "src-per", "display_name": "private", "token_tier": "per_import", "gated": None}
NO_TIER = {"id": "src-notier", "display_name": "x", "gated": None}
NULL_TIER = {"id": "src-null", "display_name": "x", "token_tier": None, "gated": None}
ODD_TIER = {"id": "src-odd", "display_name": "x", "token_tier": "borrowed", "gated": None}
GATED = {"id": "src-gated", "display_name": "x", "token_tier": "none", "gated": "auto"}
HIDDEN = [STORED, PER_IMPORT, NO_TIER, NULL_TIER, ODD_TIER, GATED]
ALL = {s["id"]: s for s in [OPEN, *HIDDEN]}


def fake() -> FakeApp:
    app = FakeApp("midataworks")
    app.on(
        "GET",
        "/api/v1/sources/{source_id}",
        lambda r: ALL.get(r.path_params["source_id"])
        or app.error(404, "not_found", "no such source"),
    )
    app.on("GET", "/api/v1/sources/{source_id}/rows", {"rows": [{"text": "a row"}], "total": 1})
    app.on("GET", "/api/v1/sources/{source_id}/profile", {"columns": ["text"]})
    app.on("POST", "/api/v1/versions", {"id": "ver-1", "status": "building"})
    return no_pending(app)


def client(app: FakeApp) -> Any:
    return client_for(app, registry=test_registry())


async def call(app: FakeApp, route_id: str, **kw: Any) -> Any:
    registry = test_registry()
    return await client(app).call(registry.get(route_id), **kw)


def test_the_check_route_is_in_the_live_registry() -> None:
    route = ROUTES.get(GET_SOURCE)
    assert (route.app, route.method, route.path) == (
        "midataworks",
        "GET",
        "/api/v1/sources/{source_id}",
    )


@pytest.mark.parametrize("source", HIDDEN, ids=lambda s: s["id"])
def test_only_an_uncredentialed_ungated_source_is_showable(source: dict[str, Any]) -> None:
    assert showable(OPEN)
    assert not showable(source)


# -- list -------------------------------------------------------------------------------------


@pytest.mark.parametrize("envelope", ["items", "bare"])
async def test_list_drops_every_credentialed_or_unknown_source(envelope: str) -> None:
    app = FakeApp("midataworks")
    rows = [OPEN, *HIDDEN]
    app.on("GET", "/api/v1/sources", {"items": rows, "total": 7} if envelope == "items" else rows)
    answer = await call(app, "midataworks.fixture_list_sources")
    items = answer.body["items"] if envelope == "items" else answer.body
    assert [s["id"] for s in items] == ["src-open"]


async def test_list_control_keeps_open_sources() -> None:
    app = FakeApp("midataworks").on("GET", "/api/v1/sources", {"items": [OPEN, OPEN]})
    answer = await call(app, "midataworks.fixture_list_sources")
    assert len(answer.body["items"]) == 2


async def test_list_in_an_unknown_shape_is_refused() -> None:
    app = FakeApp("midataworks").on("GET", "/api/v1/sources", {"something": 1})
    with pytest.raises(MiAssistError) as caught:
        await call(app, "midataworks.fixture_list_sources")
    assert caught.value.code == "source_unchecked"


# -- one source ---------------------------------------------------------------------------------


@pytest.mark.parametrize("source", HIDDEN, ids=lambda s: s["id"])
async def test_get_refuses(source: dict[str, Any]) -> None:
    with pytest.raises(MiAssistError) as caught:
        await call(fake(), GET_SOURCE, path_params={"source_id": source["id"]})
    assert caught.value.code == "source_needs_operator"


async def test_get_control() -> None:
    answer = await call(fake(), GET_SOURCE, path_params={"source_id": "src-open"})
    assert answer.body["id"] == "src-open"


# -- rows and preview: checked BEFORE the route is called -----------------------------------


@pytest.mark.parametrize(
    "route_id,template",
    [
        ("midataworks.fixture_source_rows", "/api/v1/sources/{source_id}/rows"),
        ("midataworks.fixture_source_profile", "/api/v1/sources/{source_id}/profile"),
    ],
)
@pytest.mark.parametrize("source", HIDDEN, ids=lambda s: s["id"])
async def test_rows_and_preview_refused_before_sending(
    route_id: str, template: str, source: dict[str, Any]
) -> None:
    app = fake()
    with pytest.raises(MiAssistError) as caught:
        await call(app, route_id, path_params={"source_id": source["id"]})
    assert caught.value.code == "source_needs_operator"
    assert app.calls("GET", template) == [], "the route was reached"
    assert len(app.calls("GET", "/api/v1/sources/{source_id}")) == 1


@pytest.mark.parametrize(
    "route_id,template",
    [
        ("midataworks.fixture_source_rows", "/api/v1/sources/{source_id}/rows"),
        ("midataworks.fixture_source_profile", "/api/v1/sources/{source_id}/profile"),
    ],
)
async def test_rows_and_preview_control(route_id: str, template: str) -> None:
    app = fake()
    await call(app, route_id, path_params={"source_id": "src-open"})
    (checked,) = app.calls("GET", "/api/v1/sources/{source_id}")
    assert checked.path_params == {"source_id": "src-open"}
    assert len(app.calls("GET", template)) == 1


async def test_unreadable_source_is_refused_before_sending() -> None:
    app = fake()
    with pytest.raises(MiAssistError) as caught:
        await call(app, "midataworks.fixture_source_rows", path_params={"source_id": "src-gone"})
    assert caught.value.code == "source_unchecked"
    assert app.calls("GET", "/api/v1/sources/{source_id}/rows") == []


# -- build and version inputs ---------------------------------------------------------------


def build_body(*ids: str) -> dict[str, Any]:
    return {
        "dataset_id": "ds-1",
        "recipe_revision_id": "rr-1",
        "inputs": [{"kind": "source", "source_id": i} for i in ids],
    }


@pytest.mark.parametrize("source", HIDDEN, ids=lambda s: s["id"])
async def test_build_input_refused_before_sending(source: dict[str, Any]) -> None:
    app = fake()
    with pytest.raises(MiAssistError) as caught:
        await call(
            app, "midataworks.fixture_build_version", json=build_body("src-open", source["id"])
        )
    assert caught.value.code == "source_needs_operator"
    assert app.calls("POST") == [], "the build was sent"


async def test_build_input_control() -> None:
    app = fake()
    await call(app, "midataworks.fixture_build_version", json=build_body("src-open"))
    (sent,) = app.calls("POST", "/api/v1/versions")
    assert sent.body["inputs"] == [{"kind": "source", "source_id": "src-open"}]


async def test_a_list_field_of_source_ids_is_checked() -> None:
    app = fake()
    body = {**build_body("src-open"), "benchmark_source_ids": ["src-open", "src-stored"]}
    with pytest.raises(MiAssistError) as caught:
        await call(app, "midataworks.fixture_build_version", json=body)
    assert caught.value.code == "source_needs_operator"
    assert app.calls("POST") == []


# -- an answer that embeds a source record ----------------------------------------------------


async def test_an_import_answer_handing_over_the_operators_source_is_refused() -> None:
    """OR3-022-1's first path: the full-SHA import answers 200 with the operator's source."""
    from miassist.adapters.base import PublicCheck, issue_public_check

    app = FakeApp("midataworks").on("POST", "/api/v1/sources/hf", {"source": STORED})
    check: PublicCheck = issue_public_check("evalfx/public", True, 10, "mit")
    with pytest.raises(MiAssistError) as caught:
        await call(
            app,
            "midataworks.fixture_import",
            json={"repo_id": "evalfx/public"},
            public_check=check,
        )
    assert caught.value.code == "source_needs_operator"


def test_an_embedded_list_drops_hidden_sources() -> None:
    from miassist.adapters.base import Resource
    from miassist.adapters.midataworks import screen_answer

    answer = screen_answer(
        test_registry().get("midataworks.fixture_import"),
        Resource("midataworks", 200, {"imported": [OPEN, STORED], "n": 2}),
    )
    assert isinstance(answer, Resource)
    assert answer.body["imported"] == [OPEN]


async def test_a_refused_answer_is_never_returned_as_data() -> None:
    """Wiring through the transport: the raw answer with the operator's source never surfaces."""
    app = FakeApp("midataworks").on(
        "GET",
        "/api/v1/sources/{source_id}",
        lambda _r: httpx.Response(200, json=STORED),
    )
    with pytest.raises(MiAssistError):
        await call(app, GET_SOURCE, path_params={"source_id": "src-stored"})
