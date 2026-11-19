"""Core's lineage screen of a version (R3 review fix OR3-int-1, 2026-11-16; OVN-miassist-int-23).

``check_version_sources`` reads what miDataworks records as a version's lineage: the manifest's
``sources`` (transitive through input versions AND rule_source ancestors) and ``/lineage``'s input
versions and ``rule_sources``, walked, and screens every source with Core's rule."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from miassist.adapters.base import Unavailable
from miassist.adapters.midataworks import LINEAGE_MAX_VERSIONS, check_version_sources
from miassist.errors import MiAssistError
from tests.support.clients import client_for
from tests.support.fake_apps import FakeApp

PUBLIC = {"token_tier": "none", "gated": None}


def app(
    versions: dict[str, dict[str, Any]], tiers: dict[str, dict[str, Any]] | None = None
) -> FakeApp:
    """``versions``: id -> {manifest: {...} | None, lineage: {...} | None} (None: 404)."""
    f = FakeApp("midataworks")

    def part(name: str) -> Any:
        def answer(r: Any) -> Any:
            body = versions.get(r.path_params["version_id"], {}).get(name)
            return body if body is not None else f.error(404, "NOT_FOUND", "no")

        return answer

    f.on("GET", "/api/v1/versions/{version_id}/manifest", part("manifest"))
    f.on("GET", "/api/v1/versions/{version_id}/lineage", part("lineage"))
    f.on(
        "GET",
        "/api/v1/sources/{source_id}",
        lambda r: {
            "id": r.path_params["source_id"],
            **(tiers or {}).get(r.path_params["source_id"], PUBLIC),
        },
    )
    return f


def version(sources: list[str], *, parents: list[str] = (), taught_by: list[str] = ()) -> Any:
    return {
        "manifest": {
            "version_id": "v",
            "inputs": [{"kind": "source", "source_id": s} for s in sources[:1]],
            "sources": [{"source_id": s} for s in sources],
        },
        "lineage": {
            "inputs": [{"kind": "version", "version_id": p} for p in parents],
            "rule_sources": [{"version_id": t, "number": 1} for t in taught_by],
        },
    }


async def screen(f: FakeApp, version_id: str = "v") -> Any:
    return await check_version_sources(client_for(f), version_id)


async def test_a_public_lineage_passes_and_every_source_is_read() -> None:
    f = app({"v": version(["s1", "s2"], taught_by=["t"]), "t": version(["s3"])})
    assert await screen(f) is None
    read = sorted(r.path_params["source_id"] for r in f.calls("GET", "/api/v1/sources/{source_id}"))
    assert read == ["s1", "s2", "s3"]


@pytest.mark.parametrize("where", ["manifest_sources", "rule_source", "input_version"])
async def test_a_credentialed_source_anywhere_in_the_lineage_refuses(where: str) -> None:
    tiers = {"bad": {"token_tier": "stored", "gated": None}}
    if where == "manifest_sources":  # recorded transitively, its ancestor not listed
        versions = {"v": version(["ok", "bad"])}
    elif where == "rule_source":
        versions = {"v": version(["ok"], taught_by=["t"]), "t": version(["bad"])}
    else:
        versions = {"v": version(["ok"], parents=["p"]), "p": version(["bad"])}
    with pytest.raises(MiAssistError) as caught:
        await screen(app(versions, tiers))
    assert caught.value.code == "source_needs_operator"


@pytest.mark.parametrize(
    "versions",
    [
        {"v": {"manifest": None, "lineage": {"inputs": [], "rule_sources": []}}},
        {"v": {**version(["ok"]), "lineage": None}},
        {"v": {**version([]), "lineage": {"inputs": [], "rule_sources": []}}},
        {"v": {"manifest": {"sources": "ok"}, "lineage": version(["ok"])["lineage"]}},
        {"v": {"manifest": {"sources": [{"id": "ok"}]}, "lineage": version(["ok"])["lineage"]}},
        {"v": {**version(["ok"]), "lineage": {"inputs": [], "rule_sources": [{"number": 1}]}}},
        {"v": version(["ok"], taught_by=["gone"])},
    ],
    ids=[
        "no-manifest",
        "no-lineage",
        "no-sources",
        "sources-not-a-list",
        "item-without-id",
        "rule-source-without-id",
        "ancestor-unreadable",
    ],
)
async def test_an_unreadable_lineage_refuses(versions: dict[str, Any]) -> None:
    with pytest.raises(MiAssistError) as caught:
        await screen(app(versions))
    assert caught.value.code == "source_unchecked"


async def test_a_cycle_ends_and_a_chain_past_the_cap_refuses() -> None:
    assert (
        await screen(
            app({"v": version(["ok"], parents=["w"]), "w": version(["ok"], parents=["v"])})
        )
        is None
    )
    chain = {
        f"v{i}": version(["ok"], parents=[f"v{i + 1}"]) for i in range(LINEAGE_MAX_VERSIONS + 1)
    }
    chain[f"v{LINEAGE_MAX_VERSIONS + 1}"] = version(["ok"])
    with pytest.raises(MiAssistError) as caught:
        await screen(app(chain), "v0")
    assert caught.value.code == "source_unchecked"


async def test_the_app_stopping_is_unavailable() -> None:
    f = app({"v": version(["ok"])})

    def down(r: Any) -> Any:
        raise httpx.ConnectError("gone")

    f.on("GET", "/api/v1/versions/{version_id}/lineage", down)
    assert isinstance(await screen(f), Unavailable)
