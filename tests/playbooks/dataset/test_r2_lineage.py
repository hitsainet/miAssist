"""A version is used only when every source in its lineage may be shown (R2 review fix OR2-int-6,
2026-11-16; OVN-miassist-int-23).

Core's credential screen (OVN-miassist-core-32) already refused every 004 path that NAMES a source.
Check and publish name a version: a version the operator built from a source imported with a
credential could be checked and filed for ``hub_push`` through miAssist. Now check, publish and a
build that adopts an existing version screen every source of the version's lineage with Core's
rule (``source_needs_operator``); an unreadable lineage is refused (``source_unchecked``). Nothing
is written in either case.

R3 review fix (OR3-int-1), 2026-11-16: the lineage is what miDataworks records, the manifest's
transitive ``sources`` and ``/lineage``'s input versions and ``rule_sources`` (Core's
``check_version_sources``). A ``rule_source`` ancestor is never in ``VersionOut.inputs``; the fake
serves it only where miDataworks does (``Dataworks.rule_sources``).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.playbooks.dataset.fake import PUBLIC, Dataworks, writes
from tests.playbooks.dataset.support import Session, data

REPO = "evalfx-org/published"


def world(tier: str | None = "stored") -> tuple[Dataworks, dict[str, Any], dict[str, Any]]:
    """A built version (``seed_built``) and a credentialed source beside it."""
    dw_ = Dataworks()
    seeded = dw_.seed_built()
    private = dw_._source("evalfx-org/private-upload")
    private["token_tier"] = tier
    return dw_, seeded, private


def through_a_version(dw_: Dataworks, seeded: dict[str, Any], kind: str, source_id: str) -> str:
    """The seeded version reads another version (``kind: version``, in its inputs) or had its rules
    taught by one (``rule_source``: recorded beside the inputs, never in them); that version reads
    ``source_id``."""
    ancestor = dw_._version(seeded["dataset"], 100, [{"kind": "source", "source_id": source_id}])
    version = seeded["version"]
    version["inputs"] = [{"kind": "source", "source_id": seeded["source"]["id"]}]
    if kind == "version":
        version["inputs"].append({"kind": "version", "version_id": ancestor["id"]})
    else:
        dw_.rule_sources[version["id"]] = [ancestor["id"]]
    seeded["dataset"]["head_version_id"] = version["id"]
    return ancestor["id"]


async def calls(dw_: Dataworks, name: str) -> list[tuple[str, Any, list[Any]]]:
    out = []
    for tool, args in (
        ("miassist_dataset_check", {"dataset": name}),
        ("miassist_dataset_publish", {"dataset": name, "repo_id": REPO, "confirm": True}),
    ):
        async with Session(dw_) as s:
            result = await s.call(tool, args)
        out.append((tool, result, writes(s.app)))
    return out


@pytest.mark.parametrize("tier", ["stored", "per_import", None])
async def test_a_version_built_from_a_credentialed_source_is_refused(tier: str | None) -> None:
    dw_, seeded, private = world(tier)
    seeded["version"]["inputs"] = [{"kind": "source", "source_id": private["id"]}]
    for tool, result, written in await calls(dw_, seeded["dataset"]["name"]):
        assert result.is_error and "source_needs_operator" in str(result.content), (tool, result)
        assert written == [], (tool, written)
        assert private["id"] not in str(result.content)


@pytest.mark.parametrize("kind", ["version", "rule_source"])
async def test_a_credentialed_source_through_an_input_version_is_refused(kind: str) -> None:
    dw_, seeded, private = world()
    through_a_version(dw_, seeded, kind, private["id"])
    for tool, result, written in await calls(dw_, seeded["dataset"]["name"]):
        assert result.is_error and "source_needs_operator" in str(result.content), (tool, result)
        assert written == [], (tool, written)


@pytest.mark.parametrize("which", ["manifest", "lineage", "ancestor"])
async def test_an_unreadable_lineage_is_refused(which: str) -> None:
    """The manifest or the lineage of the version, or of an ancestor, cannot be read."""
    dw_, seeded, _ = world()
    ancestor = through_a_version(dw_, seeded, "rule_source", seeded["source"]["id"])
    target = {"manifest": seeded["version"]["id"], "lineage": seeded["version"]["id"]}.get(
        which, ancestor
    )
    route = "lineage" if which == "lineage" else "manifest"
    real = dw_.manifest if route == "manifest" else dw_.lineage

    def gone(r: Any) -> Any:
        if r.path_params["version_id"] == target:
            return dw_.fake.error(404, "not_found", "no such version")
        return real(r)

    for tool, args in (
        ("miassist_dataset_check", {"dataset": seeded["dataset"]["name"]}),
        ("miassist_dataset_publish", {"dataset": seeded["dataset"]["name"], "repo_id": REPO}),
    ):
        async with Session(dw_) as s:
            s.app.on("GET", f"/api/v1/versions/{{version_id}}/{route}", gone)
            result = await s.call(tool, {**args, "confirm": True} if "repo_id" in args else args)
        assert result.is_error and "source_unchecked" in str(result.content), (tool, result)
        assert writes(s.app) == [], tool


async def test_the_reviewers_rule_source_probe_is_refused() -> None:
    """R3 review (OR3-int-1, probe ``test_r3_rule_source.py``): the version's inputs are one public
    source, as miDataworks serves it; its rules were taught by a version built from a credentialed
    source. The hub_push used to be filed; now it is refused with nothing written."""
    dw_, seeded, private = world()
    through_a_version(dw_, seeded, "rule_source", private["id"])
    assert seeded["version"]["inputs"] == [{"kind": "source", "source_id": seeded["source"]["id"]}]
    async with Session(dw_) as s:
        result = await s.call(
            "miassist_dataset_publish",
            {"dataset": seeded["dataset"]["name"], "repo_id": REPO, "confirm": True},
        )
    assert result.is_error and "source_needs_operator" in str(result.content), result
    assert writes(s.app) == [], "a publish was built or filed"


async def test_a_showable_lineage_through_an_input_version_is_used() -> None:
    dw_, seeded, _ = world()
    through_a_version(dw_, seeded, "version", seeded["source"]["id"])
    async with Session(dw_) as s:
        got = data(await s.call("miassist_dataset_check", {"dataset": seeded["dataset"]["name"]}))
    assert got["state"] == "awaiting_publish_checks"
    reads = [
        r.path_params["version_id"] for r in s.log("GET", "/api/v1/versions/{version_id}/lineage")
    ]
    assert seeded["version"]["inputs"][1]["version_id"] in reads, "the input version was not read"
    sources = [r.path_params["source_id"] for r in s.log("GET", "/api/v1/sources/{source_id}")]
    assert sources.count(seeded["source"]["id"]) >= 1, "the lineage's source was not screened"


async def test_a_build_does_not_adopt_an_existing_version_with_a_credentialed_lineage() -> None:
    dw_, seeded, private = world()
    through_a_version(dw_, seeded, "version", private["id"])
    async with Session(dw_) as s:
        result = await s.call("miassist_dataset_build", {"source": PUBLIC})
    assert result.is_error and "source_needs_operator" in str(result.content), result
    assert writes(s.app) == []


async def test_a_cycle_ends_and_a_lineage_past_the_cap_is_refused() -> None:
    from miassist.adapters.midataworks import LINEAGE_MAX_VERSIONS

    dw_, seeded, _ = world()
    first = seeded["version"]
    loop = dw_._version(seeded["dataset"], 10, [{"kind": "version", "version_id": first["id"]}])
    first["inputs"] = [*first["inputs"], {"kind": "version", "version_id": loop["id"]}]
    seeded["dataset"]["head_version_id"] = first["id"]
    async with Session(dw_) as s:
        got = data(await s.call("miassist_dataset_check", {"dataset": seeded["dataset"]["name"]}))
    assert got["state"] == "awaiting_publish_checks"

    dw_, seeded, _ = world()
    source = {"kind": "source", "source_id": seeded["source"]["id"]}
    below = dw_._version(seeded["dataset"], 10, [source])
    for _ in range(LINEAGE_MAX_VERSIONS + 1):  # the head reads 65 versions below it
        below = dw_._version(
            seeded["dataset"], 10, [{"kind": "version", "version_id": below["id"]}]
        )
    seeded["dataset"]["head_version_id"] = below["id"]
    async with Session(dw_) as s:
        result = await s.call("miassist_dataset_check", {"dataset": seeded["dataset"]["name"]})
    assert result.is_error and "source_unchecked" in str(result.content), result
    assert writes(s.app) == []


@pytest.mark.parametrize("tool", ["check", "publish"])
async def test_midataworks_stopping_during_the_walk_is_unavailable_and_sends_nothing(
    tool: str,
) -> None:
    dw_, seeded, _ = world()
    through_a_version(dw_, seeded, "version", seeded["source"]["id"])
    ancestor = seeded["version"]["inputs"][1]["version_id"]

    def version(r: Any) -> Any:
        if r.path_params["version_id"] == ancestor:
            raise httpx.ConnectError("miDataworks stopped answering")
        return dw_.manifest(r)

    args: dict[str, Any] = {"dataset": seeded["dataset"]["name"]}
    if tool == "publish":
        args |= {"repo_id": REPO, "confirm": True}
    async with Session(dw_) as s:
        s.app.on("GET", "/api/v1/versions/{version_id}/manifest", version)
        result = await s.call(f"miassist_dataset_{tool}", args)
    assert not result.is_error, result.content
    assert result.structured_content["unavailable"] == "midataworks"
    assert writes(s.app) == []


async def test_an_executed_publish_without_its_row_is_reported_not_filed_again() -> None:
    """R2 review (OR2-int-1, control I-pend3b), 2026-11-16: with ``executing`` now open in the merged
    lookup, publish's own search of finished outcomes is what keeps an ``executed`` hub_push whose
    publish row the list does not show (yet) from being filed a second time."""
    dw_ = Dataworks()
    name = dw_.seed_built()["dataset"]["name"]
    async with Session(dw_) as s:
        args = {"dataset": name, "repo_id": REPO, "confirm": True}
        await s.call("miassist_dataset_publish", args)
        dw_.decide("executed", row=False)
        await s.call("miassist_dataset_publish", args)
    assert len(s.log("POST", "/api/v1/publishes")) == 1, "a second hub_push was filed"
