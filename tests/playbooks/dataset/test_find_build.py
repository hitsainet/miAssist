"""Find and build against a fake miDataworks, on the request log (004 FTASKS 2.1-2.4, 3.1-3.6;
FPRD FR-004.6, FR-004.7, FR-004.10 - FR-004.12, FR-004.17, FR-004.18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from miassist.adapters import dataset as dw
from miassist.adapters.base import Resource, issue_public_check
from miassist.errors import MiAssistError
from tests.playbooks.dataset.fake import GATED, PRIVATE, PUBLIC, Dataworks, hub_item, writes
from tests.playbooks.dataset.support import Session, data
from tests.support import shapes

SEARCH = "/api/v1/sources/hf/search"
PREVIEW = "/api/v1/sources/hf/preview"
IMPORT = "/api/v1/sources/hf"

# -- find (2.x) ---------------------------------------------------------------------------------


async def find(dw_: Dataworks, **args: Any) -> tuple[Session, Any]:
    async with Session(dw_) as s:
        result = await s.call("miassist_dataset_find", {"query": "support chats", **args})
    return s, result


async def test_find_public_candidate_is_shown_and_previewed() -> None:
    s, result = await find(Dataworks(hub=[hub_item(PRIVATE, private=True), hub_item(PUBLIC)]))
    got = data(result)
    assert [c["repo_id"] for c in got["candidates"]] == [PUBLIC]
    assert got["dropped_count"] == 1
    assert got["preview"]["repo_id"] == PUBLIC and got["preview"]["columns"] == ["text", "label"]
    assert got["candidates"][0]["rows"] == 48_200 and got["candidates"][0]["splits"] == ["train"]
    assert "with credit" in got["candidates"][0]["licence_plain"]
    text = json.dumps(result.structured_content)
    assert PRIVATE not in text and "SECRET-ROW-TEXT" not in text
    # one candidate search with the person's words, the exact-repo check, one preview after it
    searches = s.log("POST", SEARCH)
    assert [r.body["query"] for r in searches] == ["support chats", PUBLIC]
    assert [r.body["repo_id"] for r in s.log("POST", PREVIEW)] == [PUBLIC]
    order = [r.template for r in s.app.requests if r.template in (SEARCH, PREVIEW)]
    assert order == [SEARCH, SEARCH, PREVIEW]
    assert writes(s.app) == [("POST", SEARCH), ("POST", SEARCH), ("POST", PREVIEW)]
    assert result.structured_content["next_steps"][0] == {
        "tool": "miassist_dataset_build",
        "args": {"source": PUBLIC},
        "why": result.structured_content["next_steps"][0]["why"],
    }


async def test_find_private_and_gated_show_nothing_and_preview_nothing() -> None:
    s, result = await find(
        Dataworks(hub=[hub_item(PRIVATE, private=True), hub_item(GATED, gated=True)])
    )
    got = data(result)
    assert got["candidates"] == [] and got["dropped_count"] == 2 and "preview" not in got
    assert s.log("POST", PREVIEW) == []
    assert len(s.log("POST", SEARCH)) == 1
    text = json.dumps(result.structured_content)
    assert PRIVATE not in text and GATED not in text


async def test_find_sends_no_token_and_the_licence_filter() -> None:
    s, _ = await find(Dataworks(), licence="redistributable")
    for r in s.app.requests:
        assert "access_token" not in (r.body or {}), r.template
        assert r.headers["x-dataworks-agent"] == "agent:miassist"
    assert s.log("POST", SEARCH)[0].body["licences"] == [
        "cc-by-4.0",
        "cc-by-sa-4.0",
        "cc0-1.0",
        "mit",
        "apache-2.0",
    ]


async def test_find_hub_timeout_is_a_retryable_teaching_error() -> None:
    dw_ = Dataworks()
    async with Session(dw_) as s:
        s.app.on("POST", SEARCH, lambda r: s.app.error(504, "search_timeout", "slow hub"))
        result = await s.call("miassist_dataset_find", {"query": "x"})
    assert result.is_error
    text = result.content[0].text
    assert text.startswith("hf_timeout:") and "miassist_dataset_find" in text
    assert "unavailable" not in text


# -- build (3.x) --------------------------------------------------------------------------------


async def build(dw_: Dataworks, s: Session, **args: Any) -> Any:
    return await s.call("miassist_dataset_build", {"source": PUBLIC, **args})


async def test_build_public_end_to_end_with_the_default_recipe() -> None:
    dw_ = Dataworks()
    async with Session(dw_) as s:
        got = data(await build(dw_, s, label_column="label"))
    assert got["state"] == "version_ready" and got["version_ready"] is True
    assert got["version"]["total_rows"] == 48_000 and got["dataset_name"] == "support-chats"
    saved = s.log("POST", "/api/v1/recipes")[0].body
    assert saved["name"] == "support-chats"
    assert [st["operator"] for st in saved["body"]["steps"]] == ["dedup_exact", "split"]
    assert all(st["version"] == "1.2.0" for st in saved["body"]["steps"])
    assert saved["body"]["steps"][1]["params"]["stratify_by"] == ["label"]
    seen = [(r.method, r.template) for r in s.app.requests]
    assert seen.index(("POST", "/api/v1/versions/plan")) < seen.index(("POST", "/api/v1/versions"))
    assert seen.index(("POST", "/api/v1/recipes/validate")) < seen.index(
        ("POST", "/api/v1/recipes")
    )
    assert [r.path_params["name"] for r in s.log("GET", "/api/v1/operators/{name}")] == [
        "dedup_exact",
        "split",
    ]
    imported = s.log("POST", IMPORT)
    assert len(imported) == 1 and imported[0].body == {"repo_id": PUBLIC}
    assert s.log("POST", "/api/v1/datasets")[0].body == {
        "name": "support-chats",
        "target_type": "untyped",
    }
    build_body = s.log("POST", "/api/v1/versions")[0].body
    assert build_body["inputs"][0]["kind"] == "source" and build_body["seed"] == 0
    for r in s.app.requests:
        assert r.headers["x-dataworks-agent"] == "agent:miassist"
        assert "approval" not in json.dumps(r.headers).lower() or r.method == "GET"


async def test_build_twice_writes_once_per_action() -> None:
    dw_ = Dataworks()
    async with Session(dw_) as s:
        data(await build(dw_, s))
        first = writes(s.app)
        s.app.requests.clear()
        again = data(await build(dw_, s))
        second = writes(s.app)
    assert again["state"] == "version_ready"
    assert ("POST", IMPORT) in first and ("POST", "/api/v1/versions") in first
    assert second == [], second


@pytest.mark.parametrize("repo", [PRIVATE, GATED, "evalfx-org/not-on-the-hub"])
async def test_build_private_gated_or_missing_is_the_operators(repo: str) -> None:
    dw_ = Dataworks(hub=[hub_item(PRIVATE, private=True), hub_item(GATED, gated=True)])
    async with Session(dw_) as s:
        got = data(await s.call("miassist_dataset_build", {"source": repo}))
    assert got["state"] == "awaiting_import"
    assert (
        got["waiting"] == [{"kind": "operator_action", "detail": got["waiting"][0]["detail"]}]
        and repo in got["waiting"][0]["detail"]
    )
    # the playbook's own hand-off words, not Core's backstop (R1 review fix OR1-pb-21, N08)
    assert "so only the operator can import it" in got["waiting"][0]["detail"]
    assert s.log("POST", IMPORT) == [] and s.log("POST", PREVIEW) == []


@pytest.mark.parametrize("mode", ["large", "large_sync"])
async def test_large_import_is_one_operator_action_and_no_second_import(mode: str) -> None:
    dw_ = Dataworks(import_mode=mode)
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    assert got["state"] == "awaiting_import"
    assert got["waiting"][0]["kind"] == "operator_action"
    assert "confirm" in got["waiting"][0]["detail"] or "size" in got["waiting"][0]["detail"]
    imports = s.log("POST", IMPORT)
    assert len(imports) == 1 and "confirm_large" not in imports[0].body
    if mode == "large":
        assert "90,000,000,000 bytes" in got["waiting"][0]["detail"]


async def test_running_import_is_a_job_wait() -> None:
    dw_ = Dataworks(import_mode="running")
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    assert got["state"] == "importing" and got["waiting"][0]["kind"] == "job"
    assert s.log("POST", "/api/v1/datasets") == []


@pytest.mark.parametrize(
    "body",
    [
        {"repo_id": PUBLIC, "confirm_large": True},
        {"repo_id": PUBLIC, "confirm_large": "true"},
        {"repo_id": PUBLIC, "confirm_large": False},
        {"repo_id": PUBLIC, "access_token": "hf_evalfx"},
        {"repo_id": PUBLIC, "access_token": None},
    ],
    ids=["large-true", "large-string", "large-false", "token", "token-null"],
)
async def test_core_refuses_forbidden_import_arguments(body: dict[str, Any]) -> None:
    """3.1, A20, R3M-10: refused with forbidden_argument before sending, in any value."""
    dw_ = Dataworks()
    async with Session(dw_) as s:
        client = s.deps.runtime.clients["midataworks"]
        check = issue_public_check(PUBLIC, True, 10, "cc-by-4.0")
        with pytest.raises(MiAssistError) as refused:
            await client.call(dw.SOURCES_HF_IMPORT, json=body, public_check=check)
        assert refused.value.code == "forbidden_argument"
        assert s.app.requests == []


async def test_import_without_a_passed_check_sends_nothing() -> None:
    dw_ = Dataworks()
    async with Session(dw_) as s:
        client = s.deps.runtime.clients["midataworks"]
        answer = await client.call(dw.SOURCES_HF_IMPORT, json={"repo_id": PUBLIC})
        assert not isinstance(answer, Resource) and s.app.requests == []


async def test_a_plan_that_labels_rows_never_builds() -> None:
    dw_ = Dataworks(plan_labels=40)
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    assert got["state"] == "awaiting_operator_build"
    assert got["waiting"][0]["kind"] == "operator_action" and "40" in got["waiting"][0]["detail"]
    assert len(s.log("POST", "/api/v1/versions/plan")) == 1
    assert s.log("POST", "/api/v1/versions") == []


async def test_a_plan_that_labels_below_the_threshold_still_hands_off() -> None:
    """R1 review fix (OR1-pb-1), 2026-11-16: miDataworks nests the facts under ``labelling`` and
    waits only above its threshold (``agent_needs_approval`` false here); a counted step alone
    still makes the build the operator's."""
    dw_ = Dataworks(plan_labels=500)
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    plan = s.app.calls("POST", "/api/v1/versions/plan")
    assert len(plan) == 1
    assert got["state"] == "awaiting_operator_build" and "500" in got["waiting"][0]["detail"]
    assert s.log("POST", "/api/v1/versions") == []


@pytest.mark.parametrize(
    "plan",
    [
        {"valid": True, "counted_steps": [{"step": 2}], "rows_counted": 500},
        {"valid": True, "labelling": {"rows_counted": 500}},
    ],
)
async def test_an_unreadable_plan_never_builds(plan: dict[str, Any]) -> None:
    """R1 review fix (OR1-pb-1), 2026-11-16: fail closed when the labelling facts can't be read."""
    dw_ = Dataworks(plan_override=plan)
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    assert got["state"] == "awaiting_operator_build"
    assert "did not say whether it labels rows" in got["waiting"][0]["detail"]
    assert s.log("POST", "/api/v1/versions") == []
    off_shape = shapes.collected()  # the answer is deliberately one miDataworks does not give
    assert off_shape and all("POST /api/v1/versions/plan" in v for v in off_shape)


#: The actions a gated ``POST /versions`` can wait as; pinned below to the vendored snapshot.
BUILD_ACTIONS = ["agent_label_rows", "sensitivity_declare"]


def test_the_build_actions_are_the_snapshots() -> None:
    """The fake's gated-build actions are exactly the ones miDataworks publishes for the route
    (``x-approval-actions`` in the vendored OpenAPI pin), so a new one turns this red."""
    pins = json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures/openapi/midataworks.json").read_text()
    )
    assert pins["paths"][dw.VERSIONS.path]["post"]["x-approval-actions"] == BUILD_ACTIONS


@pytest.mark.parametrize("action", BUILD_ACTIONS)
async def test_a_gated_build_is_a_wait_and_no_second_post(action: str) -> None:
    """A19: a 202 carrying an approval is shown in the A6 shape; nothing is re-submitted. Both
    actions ``POST /versions`` publishes in ``x-approval-actions`` (miDataworks 021-P3: a build that
    lowers sensitivity waits as ``sensitivity_declare``) are the same wait."""
    dw_ = Dataworks(build_mode="approval", build_approval_action=action)
    async with Session(dw_) as s:
        result = await build(dw_, s)
        got = data(result)
    assert got["state"] == "build_waiting" and not result.is_error
    approval = result.structured_content["approval"]
    assert approval["action"] == action
    assert approval["decide_in"] == "midataworks" and approval["then"] == "server_runs"
    assert approval["status"] == "pending"
    assert len(s.log("POST", "/api/v1/versions")) == 1


async def test_build_running_answers_building() -> None:
    dw_ = Dataworks(build_mode="running")
    async with Session(dw_) as s:
        got = data(await build(dw_, s))
    assert got["state"] == "building" and got["waiting"][0]["kind"] == "job"


async def test_build_empty_names_the_top_drop_reason() -> None:
    dw_ = Dataworks(build_mode="empty")
    async with Session(dw_) as s:
        result = await build(dw_, s)
    assert result.is_error
    text = result.content[0].text
    assert text.startswith("build_empty:") and "every row was a duplicate" in text


async def test_build_failed_carries_the_reason() -> None:
    dw_ = Dataworks(build_mode="failed")
    async with Session(dw_) as s:
        result = await build(dw_, s)
    assert result.is_error and "row 3" in result.content[0].text


async def test_existing_source_by_name_is_adopted_without_import() -> None:
    dw_ = Dataworks()
    dw_._source("evalfx-org/uploaded")
    dw_.sources[next(iter(dw_.sources))]["display_name"] = "my-upload"
    async with Session(dw_) as s:
        got = data(await s.call("miassist_dataset_build", {"source": "my-upload"}))
    assert got["state"] == "version_ready"
    assert s.log("POST", IMPORT) == [] and s.log("POST", SEARCH) == []


@pytest.mark.parametrize("tier", ["stored", "per_import", None])
async def test_a_source_imported_with_a_credential_is_never_adopted(tier: str | None) -> None:
    """Integration (OVN-miassist-int-15), 2026-11-16: Core's credential screen (OVN-miassist-core-32)
    governs 004's calls too. A source the operator imported with a token (or one whose tier is
    unknown) is neither shown nor built from: the build refuses ``source_needs_operator`` and
    sends no write to miDataworks."""
    dw_ = Dataworks()
    dw_._source("evalfx-org/private-upload")
    source = dw_.sources[next(iter(dw_.sources))]
    source["display_name"] = "my-upload"
    source["token_tier"] = tier
    for named, refusal in ((source["display_name"], "source_not_found"), (source["id"], None)):
        async with Session(dw_) as s:
            result = await s.call("miassist_dataset_build", {"source": named})
        # by name: the list never shows it (hidden, never named); by id: refused by its read
        assert result.is_error, result.content
        assert (refusal or "source_needs_operator") in str(result.content), result.content
        assert [c for c in s.log() if c.method != "GET"] == [], "a write was sent"


async def test_expert_recipe_is_validated_and_saved_as_given() -> None:
    body = {
        "format": "dw.recipe/v1",
        "steps": [{"operator": "dedup_exact", "version": "1.0.0", "params": {}}],
    }
    dw_ = Dataworks()
    async with Session(dw_) as s:
        data(await build(dw_, s, recipe=body))
    assert s.log("POST", "/api/v1/recipes")[0].body["body"] == body
    assert len(s.log("POST", "/api/v1/operators/{name}/{version}/validate")) == 1
    assert s.log("GET", "/api/v1/operators/{name}") == []


async def test_no_token_argument_in_any_schema() -> None:
    async with Session(Dataworks()) as s:
        tools = await s._client.list_tools()
    for tool in tools.tools:
        if tool.name.startswith("miassist_dataset_"):
            props = json.dumps(tool.input_schema).lower()
            assert "token" not in props and "confirm_large" not in props, tool.name


async def test_every_fake_answer_is_checked_against_midataworks_shapes() -> None:
    """R1 review fix (OR1-pb-1), 2026-11-16: the fake is a ShapedFakeApp and checked every 2xx
    answer of a whole build (the wiring of the shape check, not its existence)."""
    dw_ = Dataworks()
    async with Session(dw_) as s:
        data(await build(dw_, s))
    answered = [r for r in s.app.requests if r.template is not None]
    assert isinstance(s.app, shapes.ShapedFakeApp)
    assert s.app.checked >= len(answered) - 1 > 5  # every 2xx (a 404 read is not checked)
    assert s.app.violations == []


async def test_a_plan_that_is_not_valid_never_builds() -> None:
    """R2 review fix (OR2-int-5, F08), 2026-11-16: the dry run's ``valid: false`` (the recipe does
    not fit the inputs) refuses ``recipe_invalid`` before ``POST /versions``; no test drove it."""
    dw_ = Dataworks(plan_valid=False)
    async with Session(dw_) as s:
        result = await build(dw_, s)
    assert result.is_error and "recipe_invalid" in str(result.content), result
    assert "does not fit this source" in str(result.content)
    assert len(s.log("POST", "/api/v1/versions/plan")) == 1
    assert s.log("POST", "/api/v1/versions") == []
