"""The four converging actions (004 FTDD §1, §6; FTID §3.2-§3.5).

Each reads what exists, then performs at most one converging write per action (the import, the
dataset, the recipe, the build, the files, the publish), so a repeated call converges on what is
already there (FR-004.10). Every app call goes through Core's ``AppClient`` (FR-004.17); a long job
is polled at most ``POLL_WINDOW_S`` seconds, then the answer is a wait with what to expect.

Safety, in Core's adapter, never re-checked here by reading source: the import runs only with a
passed exact-repository public check (A23), ``access_token`` and ``confirm_large`` are refused
before sending (A20, A24), the floor's rate limits and pending cap apply (A24, A37). Here: a plan
that labels rows never builds (FR-004.7); the publish is called once and then only read (A18); a
rejected or expired publish is filed again only with ``ask_again`` (FR-004.16); publishes are
private unless the person said public (A14).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from miassist.adapters import dataset as dw
from miassist.adapters.base import (
    AppClient,
    AppError,
    Handoff,
    Pending,
    PublicCheck,
    Resource,
    Unavailable,
)
from miassist.adapters.midataworks import check_version_sources
from miassist.errors import MiAssistError
from miassist.hub.public_check import public_hub_search, run_public_check
from miassist.playbooks._shared import pending
from miassist.playbooks.dataset import checks, recipe
from miassist.playbooks.dataset.flow import (
    JOB_DONE,
    JOB_FAILED,
    PUBLISH_FAILED,
    PUBLISHED,
    PUBLISHING,
    Facts,
    as_int,
    current_publish,
    derive,
)
from miassist.playbooks.dataset.snapshot import Down, find_dataset, find_version, get, items
from miassist.results.approvals import approval_object
from miassist.server.specs import Deps

POLL_WINDOW_S = 10.0
POLL_INTERVAL_S = 1.0
HF_TIMEOUTS = frozenset({"search_timeout", "preview_timeout", "http_504"})
#: I2: the licence filter, as miDataworks' own ``licences[]`` (at most 5, ``HfSearchRequest``).
LICENCE_FILTERS: dict[str, list[str]] = {
    "any": [],
    "open": ["cc0-1.0", "mit", "apache-2.0", "cc-by-4.0", "odc-by"],
    "redistributable": ["cc-by-4.0", "cc-by-sa-4.0", "cc0-1.0", "mit", "apache-2.0"],
}


@dataclass
class Ctx:
    deps: Deps
    client: AppClient
    level: str

    @property
    def words(self) -> dict[str, str]:
        return self.deps.guidance.playbooks["dataset"].texts

    def w(self, key: str, **slots: Any) -> str:
        return self.deps.guidance.render(self.words[key], slots).text

    @property
    def clients(self) -> Mapping[str, AppClient]:
        return self.deps.runtime.clients


@dataclass
class Outcome:
    state: str
    fields: dict[str, Any] = field(default_factory=dict)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    next_steps: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] | None = None
    subject: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)


def step(tool: str, args: Mapping[str, Any], why: str) -> dict[str, Any]:
    return {"tool": tool, "args": dict(args), "why": why}


def app_error(answer: Any) -> MiAssistError:
    if isinstance(answer, AppError):
        return MiAssistError(answer.code, answer.message or answer.code)
    return MiAssistError("midataworks.app_error", "miDataworks answered unexpectedly")


def hub_timeout(ctx: Ctx, answer: AppError, retry: Mapping[str, Any], tool: str) -> MiAssistError:
    return MiAssistError(
        "hf_timeout",
        ctx.w("error.hf_timeout"),
        fix=ctx.w("error.hf_timeout_fix"),
        next=[step(tool, retry, ctx.w("error.hf_timeout_fix"))],
    )


async def poll_job(ctx: Ctx, job_id: str) -> dict[str, Any]:
    """The job, read until it ends or ``POLL_WINDOW_S`` passes (the last read either way)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_WINDOW_S
    while True:
        job = await get(ctx.client, dw.JOB, path_params={"job_id": job_id}) or {}
        status = str(job.get("status") or "").lower()
        if status in JOB_DONE or status in JOB_FAILED or loop.time() >= deadline:
            return dict(job)
        await asyncio.sleep(POLL_INTERVAL_S)


def _job_handoff(job: Mapping[str, Any]) -> bool:
    text = " ".join(str(job.get(k) or "") for k in ("error", "message", "result"))
    result = job.get("result")
    code = result.get("code") if isinstance(result, Mapping) else None
    return code == "import_confirmation_required" or "import_confirmation_required" in text


def _expected_bytes(job: Mapping[str, Any]) -> int | None:
    for source in (job.get("result"), job.get("details"), job):
        if isinstance(source, Mapping):
            inner = source.get("details")
            details: Mapping[str, Any] = inner if isinstance(inner, Mapping) else source
            value = details.get("expected_bytes")
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _size(ctx: Ctx, size: int | None) -> str:
    return ctx.w("size.unknown") if size is None else ctx.w("size.bytes", bytes=f"{size:,}")


# -- find ------------------------------------------------------------------------------------------


async def converge_find(ctx: Ctx, query: str, licence: str, limit: int) -> Outcome:
    licences = LICENCE_FILTERS[licence]
    found = await public_hub_search(ctx.clients, query, limit, licences)
    if isinstance(found, Unavailable):
        raise Down(found.reason)
    if isinstance(found, AppError):
        if found.code.removeprefix("midataworks.") in HF_TIMEOUTS:
            raise hub_timeout(
                ctx,
                found,
                {"query": query, "licence": licence, "limit": limit},
                "miassist_dataset_find",
            )
        raise app_error(found)
    if not isinstance(found, tuple):
        raise app_error(found)
    kept, dropped = found
    sources = items(
        await get(ctx.client, dw.SOURCES, params={"kind": "hf", "page": 1, "limit": 50}) or {}
    )
    imported = {str(s.get("repo_id")): str(s.get("id")) for s in sources if s.get("repo_id")}
    preview: dict[str, Any] | None = None
    if kept:
        top = kept[0].repo_id
        check = await run_public_check(ctx.clients, top, with_size=False)
        if isinstance(check, PublicCheck) and check.public:
            answer = await ctx.client.call(
                ctx.client.guards.registry.get("midataworks.hf_preview"),
                json={"repo_id": top},
                public_check=check,
            )
            if (
                isinstance(answer, AppError)
                and answer.code.removeprefix("midataworks.") in HF_TIMEOUTS
            ):
                raise hub_timeout(
                    ctx,
                    answer,
                    {"query": query, "licence": licence, "limit": limit},
                    "miassist_dataset_find",
                )
            if isinstance(answer, Resource) and isinstance(answer.body, Mapping):
                body = answer.body
                preview = {
                    "repo_id": top,
                    "commit": body.get("resolved_commit"),
                    "configs": list(body.get("configs") or []),
                    "splits": [
                        {"name": s.get("name"), "rows": s.get("rows")}
                        for s in body.get("splits") or []
                        if isinstance(s, Mapping)
                    ],
                    "columns": [
                        c.get("name") if isinstance(c, Mapping) else str(c)
                        for c in body.get("columns") or []
                    ],
                }
            elif isinstance(answer, Unavailable):
                raise Down(answer.reason)
    candidates = []
    for n, cand in enumerate(kept, start=1):
        line: dict[str, Any] = {
            "repo_id": cand.repo_id,
            "licence": cand.licence,
            "licence_plain": checks.licence_plain(ctx.words, cand.licence),
            "rows": None,
            "splits": [],
        }
        if preview is not None and preview["repo_id"] == cand.repo_id:
            rows = [s["rows"] for s in preview["splits"] if isinstance(s["rows"], int)]
            line["rows"] = sum(rows) if rows else None
            line["splits"] = [s["name"] for s in preview["splits"]]
        if cand.repo_id in imported:
            line["already_imported_source_id"] = imported[cand.repo_id]
        line["line"] = ctx.w(
            "find.line",
            n=n,
            repo_id=cand.repo_id,
            rows=line["rows"] if line["rows"] is not None else ctx.w("find.rows_unknown"),
            licence=cand.licence or "-",
            plain=line["licence_plain"],
            splits=", ".join(line["splits"]) or "-",
        )
        candidates.append(line)
    fields: dict[str, Any] = {"candidates": candidates, "dropped_count": dropped}
    if preview is not None:
        fields["preview"] = preview
    lines = [c["line"] for c in candidates] or [ctx.w("find.none")]
    if dropped:
        lines.append(ctx.w("find.dropped", count=dropped))
    fields["summary_lines"] = lines
    next_steps = [
        step(
            "miassist_dataset_build",
            {"source": c["repo_id"]},
            ctx.w("find.choose_first" if i == 0 else "find.choose"),
        )
        for i, c in enumerate(candidates)
    ]
    return Outcome(
        "nothing_chosen" if not candidates else "source_chosen", fields, next_steps=next_steps
    )


# -- build -----------------------------------------------------------------------------------------


@dataclass
class BuildArgs:
    source: str
    config: str | None = None
    split: str | None = None
    revision: str | None = None
    name: str | None = None
    text_column: str | None = None
    label_column: str | None = None
    recipe: dict[str, Any] | None = None


def _is_repo(ref: str) -> bool:
    return "/" in ref and not ref.startswith("/")


async def _existing_source(ctx: Ctx, ref: str) -> dict[str, Any] | None:
    listed = items(await get(ctx.client, dw.SOURCES, params={"page": 1, "limit": 50}) or {})
    for item in listed:
        named = ref in (item.get("id"), item.get("display_name"), item.get("repo_id"))
        if named and item.get("state") in (None, "ready"):
            full = await get(ctx.client, dw.SOURCE, path_params={"source_id": item["id"]})
            return dict(full) if isinstance(full, Mapping) else dict(item)
    if not _is_repo(ref):
        full = await get(ctx.client, dw.SOURCE, path_params={"source_id": ref})
        return dict(full) if isinstance(full, Mapping) else None
    return None


async def _import(ctx: Ctx, a: BuildArgs) -> dict[str, Any] | Outcome:
    """The source, imported if public; or a wait (the operator's import, or the job)."""
    check = await run_public_check(ctx.clients, a.source, with_size=False)
    if isinstance(check, Unavailable):
        raise Down(check.reason)
    if isinstance(check, Handoff) or not (isinstance(check, PublicCheck) and check.public):
        if isinstance(check, AppError):
            raise app_error(check)
        return Outcome(
            "awaiting_import",
            {"source_id": None, "version_ready": False},
            waiting=[
                {
                    "kind": "operator_action",
                    "detail": ctx.w("wait.import_private", repo_id=a.source),
                }
            ],
            slots={"detail": ctx.w("wait.import_private", repo_id=a.source)},
        )
    body: dict[str, Any] = {"repo_id": a.source}
    for key in ("config", "split", "revision"):
        if getattr(a, key):
            body[key] = getattr(a, key)
    answer = await ctx.client.call(dw.SOURCES_HF_IMPORT, json=body, public_check=check)
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if isinstance(answer, Handoff):
        return _large(ctx, a.source, None)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise app_error(answer)
    if answer.status != 202:
        return dict(answer.body)  # 200 SourceOut: already imported
    job = await poll_job(ctx, str(answer.body.get("job_id")))
    status = str(job.get("status") or "").lower()
    if status in JOB_FAILED:
        if _job_handoff(job):
            return _large(ctx, a.source, _expected_bytes(job))
        raise MiAssistError("import_failed", str(job.get("error") or job.get("message") or status))
    if status not in JOB_DONE:
        detail = ctx.w(
            "wait.import_job",
            job_id=job.get("id") or answer.body.get("job_id"),
            status=status or "queued",
        )
        return Outcome(
            "importing",
            {
                "source_id": answer.body.get("source_id"),
                "version_ready": False,
                "job": job.get("id"),
            },
            waiting=[{"kind": "job", "detail": detail}],
        )
    raw = job.get("result")
    result: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    source_id = result.get("source_id") or answer.body.get("source_id")
    full = await get(ctx.client, dw.SOURCE, path_params={"source_id": source_id})
    if not isinstance(full, Mapping):
        raise MiAssistError("import_failed", "the imported source could not be read")
    return dict(full)


def _large(ctx: Ctx, repo_id: str, size: int | None) -> Outcome:
    detail = ctx.w("wait.import_large", repo_id=repo_id, size=_size(ctx, size))
    return Outcome(
        "awaiting_import",
        {"source_id": None, "version_ready": False},
        waiting=[{"kind": "operator_action", "detail": detail}],
        slots={"detail": detail},
    )


async def _versions(ctx: Ctx) -> dict[str, str]:
    out = {}
    for name in ("dedup_exact", "split"):
        body = await get(ctx.client, dw.OPERATOR, path_params={"name": name})
        current = body.get("current_version") if isinstance(body, Mapping) else None
        if not current:
            raise MiAssistError("operator_missing", f"miDataworks has no {name} operator")
        out[name] = str(current)
    return out


def _columns(source: Mapping[str, Any]) -> list[str]:
    for f in source.get("files") or []:
        if isinstance(f, Mapping) and isinstance(f.get("columns"), list):
            return [str(c.get("name")) if isinstance(c, Mapping) else str(c) for c in f["columns"]]
    return []


async def _validated_recipe(ctx: Ctx, body: Mapping[str, Any], columns: list[str]) -> None:
    for s in body.get("steps") or []:
        answer = await ctx.client.call(
            dw.OPERATOR_VALIDATE,
            path_params={"name": s["operator"], "version": s["version"]},
            json={"params": s.get("params") or {}, **({"columns": columns} if columns else {})},
        )
        _require_valid(answer, f"{s['operator']} {s['version']}")
    answer = await ctx.client.call(
        dw.RECIPES_VALIDATE, json={"body": dict(body), **({"columns": columns} if columns else {})}
    )
    _require_valid(answer, "the recipe")


def _require_valid(answer: Any, what: str) -> None:
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if not isinstance(answer, Resource):
        raise app_error(answer)
    body = answer.body if isinstance(answer.body, Mapping) else {}
    if body.get("valid") is False:
        errors = body.get("errors") or body.get("issues") or []
        raise MiAssistError("recipe_invalid", f"miDataworks refused {what}: {str(errors)[:200]}")


async def _dataset(ctx: Ctx, a: BuildArgs, source: Mapping[str, Any]) -> dict[str, Any]:
    name = a.name or recipe.proposed_name(
        str(source.get("repo_id") or source.get("display_name") or a.source), ()
    )
    found = await find_dataset(ctx.client, name)
    if found is not None:
        return found
    answer = await ctx.client.call(
        dw.DATASETS_CREATE, json={"name": name, "target_type": "untyped"}
    )
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise app_error(answer)
    return dict(answer.body)


async def _recipe(
    ctx: Ctx, a: BuildArgs, dataset: Mapping[str, Any], source: Mapping[str, Any]
) -> tuple[str, str, list[dict[str, Any]]]:
    """``(recipe_id, revision_id, steps)``: adopted by the dataset's name, else saved."""
    listed = items(
        await get(
            ctx.client, dw.RECIPES_LIST, params={"q": dataset["name"], "page": 1, "limit": 50}
        )
        or {}
    )
    for item in listed:
        if item.get("name") == dataset["name"] and item.get("head_revision_id"):
            return str(item["id"]), str(item["head_revision_id"]), []
    columns = _columns(source)
    if a.recipe is not None:
        body = dict(a.recipe)
    else:
        splits = [str(s) for s in source.get("splits") or []]
        body = recipe.default_recipe(splits, a.label_column, await _versions(ctx))
    await _validated_recipe(ctx, body, columns)
    answer = await ctx.client.call(
        dw.RECIPES, params={"view": "summary"}, json={"name": dataset["name"], "body": body}
    )
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise app_error(answer)
    return str(answer.body["recipe_id"]), str(answer.body["revision_id"]), list(body["steps"])


def version_fields(version: Mapping[str, Any]) -> dict[str, Any]:
    splits = []
    for s in version.get("splits") or []:
        if isinstance(s, Mapping):
            splits.append(
                {"name": s.get("name"), "rows": s.get("rows"), "held_out": bool(s.get("held_out"))}
            )
    return {
        "id": version.get("id"),
        "number": version.get("number"),
        "splits": splits,
        "total_rows": version.get("total_rows"),
        "drop_summary": list(version.get("drop_summary") or [])[:5],
    }


def _top_drop(version: Mapping[str, Any]) -> str:
    drops = [d for d in version.get("drop_summary") or [] if isinstance(d, Mapping)]
    drops.sort(key=lambda d: -(as_int(d.get("rows") or d.get("count")) or 0))
    if not drops:
        return "-"
    top = drops[0]
    return str(top.get("reason") or top.get("operator") or top.get("step") or "-")[:120]


def version_outcome(ctx: Ctx, base: dict[str, Any], version: Mapping[str, Any]) -> Outcome:
    rows = as_int(version.get("total_rows")) or 0
    fields = {**base, "version": version_fields(version), "version_ready": rows > 0}
    state = derive(Facts(version_state=str(version.get("state") or "ready"), version_rows=rows))
    if state == "build_empty":
        raise MiAssistError(
            "build_empty",
            ctx.w("state.build_empty", reason=_top_drop(version)),
            fix=ctx.w("error.build_empty_fix"),
        )
    slots = {
        "number": version.get("number"),
        "rows": rows,
    }
    return Outcome(state, fields, slots=slots, subject=str(version.get("dataset_id") or ""))


async def converge_build(ctx: Ctx, a: BuildArgs) -> Outcome:
    got: dict[str, Any] | Outcome
    if _is_repo(a.source):
        existing = await _existing_source(ctx, a.source)
        got = existing if existing is not None else await _import(ctx, a)
    else:
        named = await _existing_source(ctx, a.source)
        if named is None:
            raise MiAssistError("source_not_found", ctx.w("error.source_not_found"))
        got = named
    if isinstance(got, Outcome):
        return got
    source = got
    dataset = await _dataset(ctx, a, source)
    base: dict[str, Any] = {
        "source_id": source.get("id"),
        "dataset_id": dataset.get("id"),
        "dataset_name": dataset.get("name"),
        "version_ready": False,
    }
    if dataset.get("head_version_id"):
        version = await find_version(ctx.client, dataset, None)
        if version is not None:
            await screen_lineage(ctx, version)
            out = version_outcome(ctx, base, version)
            out.subject = str(dataset.get("id"))
            return out
    recipe_id, revision_id, steps = await _recipe(ctx, a, dataset, source)
    base["recipe"] = {"id": recipe_id, "revision_id": revision_id, "steps": steps}
    base["reasons"] = [
        ctx.w(k)
        for k in recipe.reason_keys([str(s) for s in source.get("splits") or []], a.label_column)
    ]
    build_body = {
        "dataset_id": dataset["id"],
        "recipe_revision_id": revision_id,
        "inputs": [{"kind": "source", "source_id": source["id"]}],
        "seed": 0,
    }
    plan = await ctx.client.call(dw.VERSIONS_PLAN, json=build_body)
    if isinstance(plan, Unavailable):
        raise Down(plan.reason)
    if not isinstance(plan, Resource):
        raise app_error(plan)
    if isinstance(plan.body, Mapping) and plan.body.get("valid") is False:
        raise MiAssistError("recipe_invalid", ctx.w("error.plan_invalid"))
    try:
        labels = recipe.plan_labels(plan.body)
        detail = None if labels is None else ctx.w("wait.build_labels", rows=labels)
    except recipe.PlanUnreadable:  # fail closed (OR1-pb-1): the operator builds
        detail = ctx.w("wait.build_labels_unknown")
    if detail is not None:
        return Outcome(
            "awaiting_operator_build",
            base,
            waiting=[{"kind": "operator_action", "detail": detail}],
            subject=str(dataset["id"]),
        )
    answer = await ctx.client.call(dw.VERSIONS, json=build_body)
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if isinstance(answer, Pending):  # the conditional gate fired (A19): a wait, never an error
        approval = dict(answer.approval)
        return Outcome(
            "build_waiting",
            base,
            waiting=[
                {
                    "kind": "approval",
                    "detail": ctx.w("wait.approval", approval_id=approval["id"]),
                    "approval": approval,
                }
            ],
            approval=approval,
            subject=str(dataset["id"]),
        )
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise app_error(answer)
    if answer.status != 202:
        out = version_outcome(ctx, base, answer.body)
        out.subject = str(dataset["id"])
        return out
    job_id = str(answer.body.get("job_id"))
    job = await poll_job(ctx, job_id)
    status = str(job.get("status") or "").lower()
    if status in JOB_FAILED:
        raise MiAssistError(
            "build_failed",
            ctx.w("state.build_failed", reason=str(job.get("error") or status)[:200]),
        )
    if status not in JOB_DONE:
        return Outcome(
            "building",
            {**base, "job": job_id},
            waiting=[
                {
                    "kind": "job",
                    "detail": ctx.w("wait.build_job", job_id=job_id, status=status or "queued"),
                }
            ],
            subject=str(dataset["id"]),
        )
    raw_result = job.get("result")
    result: Mapping[str, Any] = raw_result if isinstance(raw_result, Mapping) else {}
    version = await get(
        ctx.client, dw.VERSION, path_params={"version_id": result.get("version_id")}
    )
    if not isinstance(version, Mapping):
        raise MiAssistError("build_failed", ctx.w("state.build_failed", reason="-"))
    out = version_outcome(ctx, base, version)
    out.subject = str(dataset["id"])
    return out


# -- check -----------------------------------------------------------------------------------------


async def screen_lineage(ctx: Ctx, version: Mapping[str, Any]) -> None:
    """Core's credential screen over a version's whole lineage (R2 review fix OR2-int-6; R3 review
    fix OR3-int-1, 2026-11-16): the lineage is what miDataworks records (the manifest's transitive
    ``sources`` and ``/lineage``'s input versions and ``rule_sources``; Core's
    ``check_version_sources``), never ``VersionOut.inputs`` alone, which holds the build request's
    inputs only. A version whose lineage reaches a source imported with a credential is refused
    ``source_needs_operator``; one whose lineage cannot be read, ``source_unchecked``. Check,
    publish and a build that adopts an existing version pass here, so miAssist never checks or
    files a publish for a version it may not use. (Status reports a version's number and rows only,
    for a dataset miAssist itself recorded; it is not screened.)"""
    stopped = await check_version_sources(ctx.client, str(version.get("id")))
    if isinstance(stopped, Unavailable):
        raise Down(stopped.reason)


async def resolve(
    ctx: Ctx, dataset_ref: str, version_ref: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = await find_dataset(ctx.client, dataset_ref)
    if dataset is None:
        raise MiAssistError("dataset_not_found", ctx.w("error.dataset_not_found"))
    version = await find_version(ctx.client, dataset, version_ref)
    if version is None:
        raise MiAssistError(
            "version_not_built",
            ctx.w("error.version_not_built"),
            next=[step("miassist_dataset_build", {"source": dataset["name"]}, ctx.w("end.status"))],
        )
    await screen_lineage(ctx, version)
    return dataset, version


async def build_files(ctx: Ctx, version_id: str, label_column: str | None) -> tuple[str, str]:
    """``(build_id, status)``: the version files, built once (miDataworks reuses a build)."""
    body = {"label_column": label_column} if label_column else {}
    answer = await ctx.client.call(
        dw.PUBLISH_BUILDS, path_params={"version_id": version_id}, json=body
    )
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise app_error(answer)
    build_id = str(answer.body.get("build_id"))
    status = str(answer.body.get("status") or "")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_WINDOW_S
    while status.lower() not in (*JOB_DONE, "ready", *JOB_FAILED):
        if loop.time() >= deadline:
            break
        read = await get(ctx.client, dw.PUBLISH_BUILD, path_params={"build_id": build_id}) or {}
        status = str(read.get("status") or status)
        if status.lower() in (*JOB_DONE, "ready", *JOB_FAILED):
            break
        await asyncio.sleep(POLL_INTERVAL_S)
    final = "completed" if status.lower() == "ready" else status.lower()
    if final in JOB_FAILED:  # failed, cancelled: terminal (R1 review fix OR1-pb-13, 2026-11-16)
        raise MiAssistError(
            "files_failed", ctx.w("error.files_failed", build_id=build_id, status=final)
        )
    return build_id, final


async def converge_check(
    ctx: Ctx,
    dataset_ref: str,
    version_ref: str | None,
    check_run_id: str | None,
    label_column: str | None = None,
) -> Outcome:
    dataset, version = await resolve(ctx, dataset_ref, version_ref)
    version_id = str(version["id"])
    build_id, files_status = await build_files(ctx, version_id, label_column)
    leakage = await get(ctx.client, dw.LEAKAGE_REPORT, path_params={"version_id": version_id})
    shortcut = await get(
        ctx.client,
        dw.SHORTCUT_AUDIT,
        path_params={"version_id": version_id},
        params={"detail": "summary"},
    )
    check_run = None
    if check_run_id:
        check_run = await get(
            ctx.client, dw.PUBLISH_CHECK_RUN, path_params={"check_run_id": check_run_id}
        )
        if check_run is None:
            raise MiAssistError("check_run_not_found", ctx.w("error.check_run_not_found"))
    # FR-004.20: data is the same at both levels, so the plain meanings use one wording.
    lines = checks.verdict(
        ctx.words, "beginner", check_run=check_run, leakage=leakage, shortcut=shortcut
    )
    allowed = checks.push_allowed(check_run)
    complete = checks.run_complete(check_run)
    run_status = str(check_run.get("status")) if isinstance(check_run, Mapping) else None
    facts = Facts(
        version_state=str(version.get("state") or "ready"),
        version_rows=as_int(version.get("total_rows")) or 0,
        files_status=files_status,
        check_run_status=("completed" if complete else run_status),
    )
    state = derive(facts)
    tally = checks.counts(lines)
    headline = ctx.w(
        "check.headline",
        number=version.get("number"),
        green=tally["green"],
        note=tally["note"],
        amber=tally["amber"],
        refused=tally["refused"],
        not_run=tally["not_run"],
    )
    summary_lines = [headline]
    for line in lines:
        if line.outcome != "green":
            word = (
                ctx.w("check.not_run_line")
                if line.outcome == checks.NOT_RUN
                else ctx.w(f"outcome.{line.outcome}")
            )
            summary_lines.append(f"{line.id} {word}: {line.plain} {line.evidence}".strip())
    if tally["amber"] or tally["not_run"]:
        summary_lines.append(ctx.w("check.amber_blocks"))
    if tally["refused"]:
        summary_lines.append(ctx.w("check.refused_blocks"))
    if allowed is not None:
        if allowed["public"]:
            summary_lines.append(ctx.w("check.public_ok"))
        elif allowed["private"]:
            summary_lines.append(ctx.w("check.private_ok"))
    fields: dict[str, Any] = {
        "dataset_id": dataset["id"],
        "version_id": version_id,
        "build_id": build_id,
        "checks_complete": complete,
        "leakage": {"pairs": checks.leakage_pairs(leakage)},
        "checks": [line.as_dict() for line in lines],
        "publish_checks": (
            {"check_run_id": check_run_id, "push_allowed": allowed} if check_run_id else "operator"
        ),
        "summary_lines": summary_lines,
    }
    waiting = []
    if state == "awaiting_publish_checks":
        waiting.append({"kind": "operator_action", "detail": ctx.w("wait.run_checks")})
    elif state == "checking":
        detail = (
            ctx.w("wait.check_run", check_run_id=check_run_id, status=run_status)
            if check_run_id and not complete
            else ctx.w("wait.files_job", build_id=build_id)
        )
        waiting.append({"kind": "job", "detail": detail})
    if any(line.id == "C-2" and line.outcome == "refused" for line in lines):
        waiting.append({"kind": "operator_action", "detail": ctx.w("wait.hub_credential")})
    return Outcome(state, fields, waiting=waiting, subject=str(dataset["id"]))


# -- publish ---------------------------------------------------------------------------------------


def _publish_state(publish: Mapping[str, Any]) -> str:
    status = str(publish.get("status") or "")
    return (
        derive(Facts(publish_status=status))
        if status in (PUBLISHED | PUBLISHING | PUBLISH_FAILED)
        else "publishing"
    )


async def _approval_status(ctx: Ctx, approval_id: str, summary: str) -> dict[str, Any]:
    body = await get(ctx.client, dw.CORE_GET_APPROVAL, path_params={"approval_id": approval_id})
    if not isinstance(body, Mapping):
        raise MiAssistError("approval_not_found", ctx.w("error.approval_not_found"))
    return approval_object("midataworks", body, style="server_executed", summary=summary)


@dataclass
class PublishArgs:
    """No defaults that the tool does not pass (R1 review fix OR1-pb-21, 2026-11-16): the private
    default is the tool signature's (``tools.py``), the one place a test can pin it."""

    dataset: str
    repo_id: str
    version: str | None
    visibility: str
    card_prose: str | None = None
    ask_again: bool = False


def approval_summary(
    ctx: Ctx, version: Mapping[str, Any], a: PublishArgs, approval_id: str, files: int | str
) -> str:
    return ctx.w(
        "approval.summary",
        number=version.get("number"),
        dataset=version.get("dataset_name") or a.dataset,
        repo_id=a.repo_id,
        visibility_upper=a.visibility.upper(),
        files=files,
        rows=version.get("total_rows"),
        approval_id=approval_id,
    )


def _approval_outcome(
    ctx: Ctx,
    base: dict[str, Any],
    approval: dict[str, Any],
    publishes: list[dict[str, Any]],
    row: Mapping[str, Any] | None = None,
) -> Outcome:
    status = approval["status"]
    mine = [p for p in publishes if p.get("repo_id") == base["repo_id"]]
    ours = current_publish(mine, row or approval) if status in ("executing", "executed") else None
    if ours is not None:  # OR1-pb-11: this approval's own publish, never an older one
        state = _publish_state(ours)
        base = {**base, "publish_id": ours.get("id"), "publish_status": ours.get("status")}
    else:
        state = derive(Facts(approval_status=status))
    waiting: list[dict[str, Any]] = []
    next_steps: list[dict[str, Any]] = []
    if state == "publish_waiting":
        waiting.append(
            {
                "kind": "approval",
                "detail": ctx.w("wait.approval", approval_id=approval["id"]),
                "approval": approval,
            }
        )
    elif state == "publishing":
        waiting.append({"kind": "job", "detail": ctx.w("state.publishing")})
    elif state in ("rejected", "expired"):
        next_steps.append(
            step(
                "miassist_dataset_publish",
                {**base["args"], "ask_again": True},
                ctx.w("publish.retry"),
            )
        )
    elif state == "failed":
        next_steps.append(
            step(
                "miassist_dataset_publish",
                {**base["args"], "ask_again": True},
                ctx.w("publish.after_failure"),
            )
        )
    fields = {k: v for k, v in base.items() if k != "args"}
    return Outcome(
        state,
        fields,
        waiting=waiting,
        next_steps=next_steps,
        approval=approval,
        slots={"reason": approval.get("reason") or "-", "repo_id": base["repo_id"]},
    )


async def converge_publish(
    ctx: Ctx, a: PublishArgs, gate: Callable[[Ctx], Awaitable[Any]] | None = None
) -> Any:
    dataset, version = await resolve(ctx, a.dataset, a.version)
    version_id = str(version["id"])
    args = {
        "dataset": a.dataset,
        "repo_id": a.repo_id,
        "visibility": a.visibility,
        **({"version": a.version} if a.version else {}),
    }
    base: dict[str, Any] = {
        "repo_id": a.repo_id,
        "visibility": a.visibility,
        "dataset_id": dataset["id"],
        "version_id": version_id,
        "args": args,
    }
    publishes = items(
        await get(
            ctx.client, dw.PUBLISHES_LIST, params={"version_id": version_id, "page": 1, "limit": 50}
        )
        or {},
        "publishes",
    )
    wanted = {"version_id": version_id, "repo_id": a.repo_id, "visibility": a.visibility}
    open_ = await pending.open_request(ctx.client, "hub_push", fields=wanted)
    if open_ is not None:
        summary = approval_summary(ctx, version, a, str(open_.get("id")), "-")
        approval = approval_object("midataworks", open_, style="server_executed", summary=summary)
        out = _approval_outcome(ctx, base, approval, publishes, open_)
        out.subject = str(dataset["id"])
        return out
    if not a.ask_again:
        for status in ("executing", "executed", "failed", "rejected", "expired"):
            decided = await pending.find_requests(
                ctx.client, "hub_push", status=status, fields=wanted
            )
            if decided:
                summary = approval_summary(ctx, version, a, str(decided[0].get("id")), "-")
                approval = approval_object(
                    "midataworks", decided[0], style="server_executed", summary=summary
                )
                out = _approval_outcome(ctx, base, approval, publishes, decided[0])
                out.subject = str(dataset["id"])
                return out
    mine = [p for p in publishes if p.get("repo_id") == a.repo_id]
    if mine and not a.ask_again:
        state = _publish_state(mine[0])
        fields = {k: v for k, v in base.items() if k != "args"} | {
            "publish_id": mine[0].get("id"),
            "publish_status": mine[0].get("status"),
        }
        return Outcome(
            state, fields, subject=str(dataset["id"]), slots={"repo_id": a.repo_id, "reason": "-"}
        )
    if gate is not None:
        held = await gate(ctx)  # the visibility form or its teaching result; nothing written yet
        if held is not None:
            return held
        base["visibility"] = a.visibility
        base["args"]["visibility"] = a.visibility
    build_id, files_status = await build_files(ctx, version_id, None)
    if files_status not in JOB_DONE:
        fields = {k: v for k, v in base.items() if k != "args"} | {"build_id": build_id}
        return Outcome(
            "checking",
            fields,
            waiting=[{"kind": "job", "detail": ctx.w("wait.files_job", build_id=build_id)}],
            subject=str(dataset["id"]),
        )
    body: dict[str, Any] = {
        "version_id": version_id,
        "build_id": build_id,
        "repo_id": a.repo_id,
        "visibility": a.visibility,
    }
    if a.card_prose:
        body["card_prose"] = a.card_prose
    answer = await ctx.client.call(dw.PUBLISHES, json=body)
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if not isinstance(answer, Pending):
        if isinstance(answer, AppError) and answer.code.endswith("token_missing"):
            raise MiAssistError("token_missing", ctx.w("wait.hub_credential"))
        raise app_error(answer)
    files = (
        len(
            (await get(ctx.client, dw.PUBLISH_BUILD, path_params={"build_id": build_id}) or {}).get(
                "files"
            )
            or []
        )
        or "-"
    )
    approval = dict(answer.approval)
    approval["summary"] = approval_summary(ctx, version, a, approval["id"], files)[:500]
    out = _approval_outcome(ctx, base, approval, [])
    out.subject = str(dataset["id"])
    return out
