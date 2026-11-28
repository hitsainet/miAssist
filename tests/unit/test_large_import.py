"""Large public imports are the operator's (001 FR-30, AC-30.4; FTASKS 4.12; A24).

miDataworks applies its own threshold: an import it answers ``import_confirmation_required`` maps to
the operator's hand-off and no second request carries ``confirm_large``. For miWorkbench Core
applies the same threshold (``MIASSIST_LARGE_IMPORT_BYTES``, default 50,000,000,000) to the size the
public check reports; over it, or unknown, is the operator's, with zero requests to the route.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from miassist.adapters.base import ANY, GateClass, Handoff, Resource, Route, issue_public_check
from miassist.adapters.routes import CORE_ROUTES, RouteRegistry
from miassist.runtime import build_runtime
from tests.support.app_factory import settings
from tests.support.clients import FIXTURE_ROUTES, client_for
from tests.support.fake_apps import FakeApp
from tests.support.memory_store import MemoryStore

REPO = "public/fixture-dataset"
WORKBENCH_IMPORT = Route(
    id="miworkbench.fixture_hf_download",
    app="miworkbench",
    method="POST",
    path="/api/v1/fixture/datasets/download",
    gate=GateClass.UNGATED_WRITE,
    purpose="fixture Hugging Face dataset download (miWorkbench)",
    floor_entry="import.hf_miworkbench",
    forbidden=MappingProxyType({"body.access_token": ANY}),
    touches_hub=True,
    hub_repo_param="body.repo_id",
    hub_repo_type="dataset",
)


def registry() -> RouteRegistry:
    return RouteRegistry(CORE_ROUTES + FIXTURE_ROUTES + (WORKBENCH_IMPORT,))


async def workbench(size: int | None, threshold: int = 50_000_000_000) -> tuple[Any, FakeApp]:
    fake = FakeApp("miworkbench").on(
        "POST", "/api/v1/fixture/datasets/download", {"id": "evalfx-job", "status": "queued"}
    )
    client = client_for(fake, registry=registry())
    client.guards.large_import_bytes = threshold
    answer = await client.call(
        WORKBENCH_IMPORT,
        json={"repo_id": REPO},
        public_check=issue_public_check(REPO, True, size, "mit"),
    )
    return answer, fake


@pytest.mark.parametrize(
    "case,size",
    [
        ("miworkbench-over", 60_000_000_000),
        ("miworkbench-unknown-size", None),
    ],
)
async def test_handoff(case: str, size: int | None) -> None:
    answer, fake = await workbench(size)
    assert isinstance(answer, Handoff) and answer.reason == "large_import_by_operator", case
    assert fake.calls("POST", "/api/v1/fixture/datasets/download") == []


@pytest.mark.parametrize("size", [1_000_000_000, 50_000_000_000])
async def test_under_or_at_threshold_is_sent(size: int) -> None:
    answer, fake = await workbench(size)
    assert isinstance(answer, Resource)
    assert len(fake.calls("POST", "/api/v1/fixture/datasets/download")) == 1


async def test_threshold_is_the_setting() -> None:
    runtime = build_runtime(
        settings(apps="miworkbench", miworkbench_url="http://w.test", large_import_bytes=100),
        store=MemoryStore(),
    )
    assert runtime.clients["miworkbench"].guards.large_import_bytes == 100
    answer, _ = await workbench(101, threshold=100)
    assert isinstance(answer, Handoff)


async def test_midataworks_confirmation_required_is_the_operators() -> None:
    fake = FakeApp("midataworks").on(
        "POST",
        "/api/v1/sources/hf",
        lambda r: fake.error(409, "import_confirmation_required", "over the import threshold"),
    )
    client = client_for(fake)
    route = client.guards.registry.get("midataworks.fixture_import")
    answer = await client.call(
        route, json={"repo_id": REPO}, public_check=issue_public_check(REPO, True, None, "mit")
    )
    assert isinstance(answer, Handoff) and answer.reason == "import_confirmation_required"
    sent = fake.calls("POST", "/api/v1/sources/hf")
    assert len(sent) == 1 and all("confirm_large" not in (r.body or {}) for r in sent)


async def test_midataworks_import_never_sends_confirm_large() -> None:
    fake = FakeApp("midataworks").on("POST", "/api/v1/sources/hf", {"id": "evalfx-src"})
    client = client_for(fake)
    route = client.guards.registry.get("midataworks.fixture_import")
    with pytest.raises(Exception, match="forbidden_argument"):
        await client.call(
            route,
            json={"repo_id": REPO, "confirm_large": True},
            public_check=issue_public_check(REPO, True, 1, "mit"),
        )
    assert fake.requests == []


def test_route_shape_is_registrable() -> None:
    assert registry().get("miworkbench.fixture_hf_download") is WORKBENCH_IMPORT
