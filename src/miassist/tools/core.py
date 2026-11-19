"""Core's seven tools (001 FR-7, FR-8, FR-9, FR-16, FR-20, FR-23, FR-24; FPRD §4).

Every user-facing word comes from ``guidance/`` (FR-11); every app call goes through an
``AppClient`` (ADR-006); every result is built by ``results.build`` (FR-12). The level changes only
``explain`` (FR-7). An unreachable app is answered ``unavailable`` with no request to it (FR-4).
"""

import difflib
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult

from miassist.adapters.base import AppError, Pending, Resource, Unavailable
from miassist.contracts.result_language import AssistResult
from miassist.errors import MiAssistError, render
from miassist.guidance.loader import TOPICS
from miassist.logging import key_fingerprint
from miassist.playbooks import generate
from miassist.playbooks.registry import ResolvedPlaybook
from miassist.playbooks.status import PROVIDERS, StatusInvalid, validated
from miassist.results.approvals import Style, approval_object
from miassist.results.build import build, error_result
from miassist.results.honest_end import honest_end
from miassist.server.keyshim import key_from_scope
from miassist.server.specs import Deps, ToolSpec
from miassist.store.degrading import StoreUnavailable

Result = Annotated[CallToolResult, AssistResult]
Topic = Literal["start", "apps", "playbooks", "approvals", "results", "glossary", "connect"]
assert TOPICS == Topic.__args__  # type: ignore[attr-defined]


def step(tool: str, args: Mapping[str, Any], why: str) -> dict[str, Any]:
    return {"tool": tool, "args": dict(args), "why": why}


def request_key(ctx: Context[Any, Any] | None) -> str | None:
    """The key from the request's path (``/p/<key>/mcp``); ``None`` without one, and for an
    in-process call (the stateless start-here provider passes no context)."""
    if ctx is None:
        return None
    request = ctx.request_context.request
    return key_from_scope(getattr(request, "scope", None))


def key_hash_of(key: str | None) -> str | None:
    return hashlib.sha256(key.encode("ascii")).hexdigest() if key else None


async def level_for(deps: Deps, key_hash: str | None) -> str:
    if key_hash is None:
        return "beginner"
    stored = await deps.runtime.store.level(key_hash)
    return stored if stored in ("beginner", "expert") else "beginner"


def tool_error(deps: Deps, error: MiAssistError) -> CallToolResult:
    fix = error.fix or deps.guidance.fix_for(error.code)
    return error_result(render(error.code, error.message, fix, error.next))


def installed_states(deps: Deps) -> list[dict[str, Any]]:
    out = []
    for app in deps.runtime.installed.sorted():
        state = deps.runtime.detector.snapshot(app)
        entry: dict[str, Any] = {
            "app": app,
            "name": deps.guidance.app_name(app),
            "state": state.state,
        }
        if state.state == "unreachable":
            entry["reason"] = state.reason
        out.append(entry)
    return out


def offered_playbooks(deps: Deps) -> list[ResolvedPlaybook]:
    return deps.playbooks.offered if deps.playbooks is not None else []


def playbook_steps(deps: Deps) -> list[dict[str, Any]]:
    """``next_steps`` from the offered playbooks: each one's first step."""
    return [
        step(p.first_step.tool, p.first_step.args, p.title) for p in offered_playbooks(deps)
    ] or [step("miassist_guide", {"topic": "start"}, deps.guidance.why("playbooks"))]


def absent_answer(deps: Deps, playbook_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """FR-5's calm answer for a playbook that is not offered here (AC-5.3, AC-23.4): never an
    error; the sentence comes from ``honest_end()`` (FR-28)."""
    known = deps.playbooks.get(playbook_id) if deps.playbooks is not None else None
    words = deps.guidance.honest_end
    data: dict[str, Any] = {
        "playbook_id": playbook_id,
        "offered": False,
        "needs": list(known.needs) if known is not None else [],
        "offered_playbooks": [p.id for p in offered_playbooks(deps)],
    }
    if known is not None and known.needs:
        sentence = honest_end(known.needs, deps.runtime.installed, deps.guidance)
        data["honest_end"] = sentence
        data["message"] = deps.guidance.render(words.absent_answer, {"honest_end": sentence}).text
    else:
        data["message"] = words.unknown_playbook
    return data, playbook_steps(deps)


# -- miassist_guide ---------------------------------------------------------------------------


def make_guide(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_guide(
        ctx: Context[Any, Any], topic: Topic = "start", playbook: str | None = None
    ) -> Result:
        key_hash = key_hash_of(request_key(ctx))
        level = await level_for(deps, key_hash)
        names = [deps.guidance.app_name(a) for a in deps.runtime.installed.sorted()]
        slots = {
            "installed_apps": ", ".join(names) if names else "no app yet",
            "apps_list": "\n".join(
                f"- {deps.guidance.app_name(a)}: {deps.guidance.apps.apps[a].purpose}"
                for a in deps.runtime.installed.sorted()
            )
            or "-",
        }
        text = deps.guidance.render(deps.guidance.guide[topic], slots).text
        data: dict[str, Any] = {"topic": topic, "text": text, "level": level}
        listed = [
            generate.listing(deps.guidance, p, "beginner" if level == "beginner" else "expert")
            for p in offered_playbooks(deps)
        ]
        if topic == "start":
            data["installed"] = installed_states(deps)
        if topic in ("start", "playbooks"):
            data["playbooks"] = listed
        if playbook is not None:
            chosen = next((entry for entry in listed if entry["id"] == playbook), None)
            if chosen is None:
                absent, steps = absent_answer(deps, playbook)
                data.update(absent)
                return build(
                    deps.guidance,
                    tool="miassist_guide",
                    outcome="not_offered",
                    level=level,
                    data=data,
                    next_steps=steps,
                )
            data["playbook"] = chosen
            first = chosen["first_step"]
            resolved = deps.playbooks.get(playbook) if deps.playbooks is not None else None
            return build(
                deps.guidance,
                tool="miassist_guide",
                outcome="playbook",
                level=level,
                data=data,
                next_steps=[step(first["tool"], first["args"], chosen["title"])],
                terms=resolved.terms if resolved is not None else (),
            )
        return build(
            deps.guidance,
            tool="miassist_guide",
            outcome="ok",
            level=level,
            data=data,
            next_steps=[step("miassist_status", {}, deps.guidance.why("status"))],
        )

    return miassist_guide


# -- miassist_glossary ------------------------------------------------------------------------


def make_glossary(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    entries = deps.guidance.glossary

    def find(term: str) -> str | None:
        wanted = term.strip().lower()
        for key, entry in entries.items():
            names = {key, entry.term.lower(), *(a.lower() for a in entry.aliases)}
            if wanted in names:
                return key
        return None

    async def miassist_glossary(ctx: Context[Any, Any], term: str | None = None) -> Result:
        level = await level_for(deps, key_hash_of(request_key(ctx)))
        if term is None:
            data = {
                "entries": [
                    {"key": k, "term": e.term, "short": e.short} for k, e in entries.items()
                ]
            }
            return build(
                deps.guidance, tool="miassist_glossary", outcome="index", level=level, data=data
            )
        key = find(term)
        if key is None:
            near = difflib.get_close_matches(term.lower(), list(entries), n=3)
            return tool_error(
                deps,
                MiAssistError(
                    "unknown_term",
                    f"the glossary has no entry for that term; nearest: {', '.join(near) or 'none'}",
                ),
            )
        entry = entries[key]
        return build(
            deps.guidance,
            tool="miassist_glossary",
            outcome="entry",
            level=level,
            data={"entry": entry.model_dump(exclude_none=True)},
            terms=[key],
            slots={"term": entry.term},
        )

    return miassist_glossary


# -- miassist_status --------------------------------------------------------------------------


def make_status(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_status(
        ctx: Context[Any, Any], playbook: str | None = None, subject: str | None = None
    ) -> Result:
        key_hash = key_hash_of(request_key(ctx))
        level = await level_for(deps, key_hash)
        data: dict[str, Any] = {
            "installed": installed_states(deps),
            "level": level,
            "remembered": key_hash is not None,
            "key_fp": key_fingerprint(key_hash) if key_hash else None,
            "settings_store": "ok" if deps.runtime.store.available else "unavailable",
            "playbooks": [{"id": p.id, "title": p.title} for p in offered_playbooks(deps)],
        }
        next_steps = [
            step("miassist_guide", {"topic": "playbooks"}, deps.guidance.why("playbooks"))
        ]
        if playbook is not None:
            resolved = deps.playbooks.get(playbook) if deps.playbooks is not None else None
            if resolved is None or not resolved.offered:
                absent, steps = absent_answer(deps, playbook)
                data.update(absent)
                data["playbook"] = None
                return build(
                    deps.guidance,
                    tool="miassist_status",
                    outcome="not_offered",
                    level=level,
                    data=data,
                    next_steps=steps,
                )
            provider = PROVIDERS[resolved.id]
            try:
                status = validated(await provider(deps, resolved, key_hash, subject or ""))
            except StatusInvalid as exc:
                return tool_error(deps, MiAssistError("playbook_status_invalid", str(exc)[:200]))
            data["playbook"] = status
            if status["next"] is not None:
                next_steps = [status["next"]]
            return build(
                deps.guidance,
                tool="miassist_status",
                outcome="playbook_finished" if status["finished"] else "playbook",
                level=level,
                data=data,
                next_steps=next_steps,
                slots={"title": resolved.title},
            )
        return build(
            deps.guidance,
            tool="miassist_status",
            outcome="ok",
            level=level,
            data=data,
            next_steps=next_steps,
        )

    return miassist_status


# -- miassist_set_guidance / miassist_reset_my_settings ---------------------------------------


def make_set_guidance(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_set_guidance(
        ctx: Context[Any, Any], level: Literal["beginner", "expert"]
    ) -> Result:
        key_hash = key_hash_of(request_key(ctx))
        if key_hash is None:
            return build(
                deps.guidance,
                tool="miassist_set_guidance",
                outcome="not_remembered",
                level="beginner",
                data={"remembered": False, "get_a_link": "/p/new"},
                next_steps=[
                    step("miassist_guide", {"topic": "connect"}, deps.guidance.why("connect"))
                ],
            )
        try:
            await deps.runtime.store.set_level(key_hash, level)
        except StoreUnavailable:
            return build(
                deps.guidance,
                tool="miassist_set_guidance",
                outcome="unavailable",
                level="beginner",
                data=None,
                unavailable="settings_store",
                reason="the settings store is not answering",
                next_steps=[step("miassist_status", {}, deps.guidance.why("store_back"))],
            )
        return build(
            deps.guidance,
            tool="miassist_set_guidance",
            outcome="saved",
            level=level,
            data={"remembered": True, "level": level},
            slots={"level": level},
        )

    return miassist_set_guidance


def make_reset(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_reset_my_settings(ctx: Context[Any, Any]) -> Result:
        key_hash = key_hash_of(request_key(ctx))
        if key_hash is None:
            return build(
                deps.guidance,
                tool="miassist_reset_my_settings",
                outcome="not_remembered",
                level="beginner",
                data={"remembered": False},
            )
        try:
            await deps.runtime.store.forget(key_hash)
        except StoreUnavailable:
            return build(
                deps.guidance,
                tool="miassist_reset_my_settings",
                outcome="unavailable",
                level="beginner",
                data=None,
                unavailable="settings_store",
                reason="the settings store is not answering",
            )
        return build(
            deps.guidance,
            tool="miassist_reset_my_settings",
            outcome="forgotten",
            level="beginner",
            data={"forgotten": True},
        )

    return miassist_reset_my_settings


# -- miassist_overview ------------------------------------------------------------------------

#: The bounded reads per app (FTID §3.10): (list name, route id, query).
OVERVIEW_READS: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "miworkbench": [
        ("models", "miworkbench.list_models", {"page": 1, "limit": 3}),
        ("saes", "miworkbench.list_saes", {"skip": 0, "limit": 3}),
        ("datasets", "miworkbench.list_datasets", {"page": 1, "limit": 3}),
        ("probes", "miworkbench.list_probes", {}),
    ],
    "miserver": [
        ("models", "miserver.list_models", {}),
        ("probes", "miserver.probe_status", {}),
        ("clusters", "miserver.list_clusters", {}),
    ],
    "midataworks": [
        ("datasets", "midataworks.list_datasets", {"page": 1, "limit": 3}),
        ("versions", "midataworks.list_versions", {"page": 1, "limit": 3}),
    ],
    "miforge": [
        ("runs", "miforge.list_runs", {"limit": 3, "offset": 0}),
        ("packs", "miforge.list_packs", {}),
        ("checkpoints", "miforge.list_checkpoints", {"limit": 3}),
    ],
}
_LIST_KEYS = (
    "items",
    "data",
    "models",
    "saes",
    "datasets",
    "probes",
    "clusters",
    "versions",
    "runs",
    "packs",
    "checkpoints",
    "results",
)


#: R3 review fix (OR3-001-2), 2026-11-16: the code for an overview read answered in a shape
#: miAssist cannot read. Such a list is unknown, never empty (the same rule as a refused read).
UNREADABLE = "overview_unreadable"


def summarise(name: str, body: Any) -> dict[str, Any]:
    """A count and up to three names, never more (no event text, FR-27: probe status is counts).

    A body in a shape this does not recognise (no list, none of ``_LIST_KEYS`` holding one, no
    integer total; a probe status with no integer count) is ``{"error": UNREADABLE}``: it is
    unknown, never an empty list (R3 review fix OR3-001-2)."""
    if name == "probes" and isinstance(body, Mapping) and "items" not in body:
        inner = body.get("data", body)
        counts = (
            {k: v for k, v in inner.items() if isinstance(v, int) and not isinstance(v, bool)}
            if isinstance(inner, Mapping)
            else {}
        )
        if not counts:
            return {"error": UNREADABLE}
        return {"counts": counts}
    items: list[Any] | None = None
    total: int | None = None
    if isinstance(body, list):
        items = body
    elif isinstance(body, Mapping):
        for key in _LIST_KEYS:
            value = body.get(key)
            if isinstance(value, list):
                items = value
                break
            if isinstance(value, Mapping):
                nested = next((v for v in value.values() if isinstance(v, list)), None)
                if nested is not None:
                    items = nested
                    break
        for key in ("total", "count", "total_count"):
            if isinstance(body.get(key), int) and not isinstance(body.get(key), bool):
                total = body[key]
    if items is None and total is None:
        return {"error": UNREADABLE}
    items = items or []
    names = []
    for item in items[:3]:
        if isinstance(item, Mapping):
            label = item.get("name") or item.get("display_name") or item.get("id")
            if label is not None:
                names.append(str(label)[:80])
    count = total if total is not None else len(items)
    return {"count": count, "at_least": total is None and len(items) >= 3, "newest": names}


def playbook_for_empty(deps: Deps, app: str) -> ResolvedPlaybook | None:
    """AC-24.2: for an empty app, the matching playbook (an offered one, other than a start-here,
    that lists this app) if one is offered, else the app's start-here. The same at both levels
    (FR-7: the level changes only ``explain``)."""
    offered = offered_playbooks(deps)
    matching = [p for p in offered if app in p.requires_apps and not p.id.startswith("start-")]
    if matching:
        return matching[0]
    return next((p for p in offered if p.id == f"start-{app}"), None)


def make_overview(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    installed = tuple(deps.runtime.installed.sorted())

    async def miassist_overview(ctx: Context[Any, Any], app: str) -> CallToolResult:
        level = await level_for(deps, key_hash_of(request_key(ctx)))
        name = deps.guidance.app_name(app)
        reason = deps.runtime.detector.unreachable_reason(app)
        if reason is not None:
            return build(
                deps.guidance,
                tool="miassist_overview",
                outcome="unavailable",
                level=level,
                data=None,
                unavailable=app,
                reason=reason,
                slots={"app_name": name},
                next_steps=[step("miassist_status", {}, deps.guidance.why("app_back"))],
            )
        client = deps.runtime.clients[app]
        registry = client.guards.registry
        lists: dict[str, Any] = {}
        for list_name, route_id, query in OVERVIEW_READS[app]:
            try:
                answer = await client.call(registry.get(route_id), params=query or None)
            except MiAssistError as error:
                return tool_error(deps, error)
            if isinstance(answer, Unavailable):
                return build(
                    deps.guidance,
                    tool="miassist_overview",
                    outcome="unavailable",
                    level=level,
                    data=None,
                    unavailable=app,
                    reason=answer.reason,
                    slots={"app_name": name},
                    next_steps=[step("miassist_status", {}, deps.guidance.why("app_back"))],
                )
            if isinstance(answer, Resource):
                lists[list_name] = summarise(list_name, answer.body)
            elif isinstance(answer, AppError):
                lists[list_name] = {"error": answer.code}
        # R2 review fix (OR2-001-4), 2026-11-16: a refused read is unknown, never empty (and so is
        # a read in a shape miAssist cannot read: R3 review fix OR3-001-2). Only
        # lists that were read and counted can make an app empty; when every read was refused the
        # outcome says so and points at the app's state, never at a start-here.
        refused = [k for k, v in lists.items() if "error" in v]
        counted = [v for v in lists.values() if "error" not in v]
        empty = (
            not refused
            and bool(counted)
            and all(v.get("count", 1) == 0 for v in counted if "count" in v)
            and all(not any(v.get("counts", {}).values()) for v in counted if "counts" in v)
        )
        if refused and not counted:
            unreadable = all(lists[k]["error"] == UNREADABLE for k in refused)
            return build(
                deps.guidance,
                tool="miassist_overview",
                outcome="unreadable" if unreadable else "refused",
                level=level,
                data={"app": app, "lists": lists},
                slots={"app_name": name},
                next_steps=[step("miassist_status", {}, deps.guidance.why("status"))],
            )
        next_steps = [
            step(
                "miassist_guide",
                {"topic": "playbooks"},
                deps.guidance.why("next_in_app", app_name=name),
            )
        ]
        start = playbook_for_empty(deps, app) if empty else None
        if start is not None:
            next_steps = [
                step(
                    "miassist_guide",
                    {"playbook": start.id},
                    deps.guidance.why("start_playbook", title=start.title),
                )
            ]
        return build(
            deps.guidance,
            tool="miassist_overview",
            outcome="empty" if empty else ("partial" if refused else "ok"),
            level=level,
            data={"app": app, "lists": lists},
            slots={"app_name": name},
            next_steps=next_steps,
        )

    miassist_overview.__annotations__["app"] = Literal[installed] if installed else str
    miassist_overview.__annotations__["return"] = Result
    return miassist_overview


# -- miassist_approval_status -----------------------------------------------------------------

STATUS_ROUTES = {
    "miworkbench": ("miworkbench.get_approval", "request_id"),
    "miserver": ("miserver.get_approval", "approval_id"),
    "midataworks": ("midataworks.get_approval", "approval_id"),
    "miforge": ("miforge.get_approval", "approval_id"),
}


def make_approval_status(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    installed = tuple(deps.runtime.installed.sorted())

    async def miassist_approval_status(
        ctx: Context[Any, Any], app: str, approval_id: str
    ) -> CallToolResult:
        level = await level_for(deps, key_hash_of(request_key(ctx)))
        reason = deps.runtime.detector.unreachable_reason(app)
        if reason is not None:
            return build(
                deps.guidance,
                tool="miassist_approval_status",
                outcome="unavailable",
                level=level,
                data=None,
                unavailable=app,
                reason=reason,
            )
        client = deps.runtime.clients[app]
        route_id, param = STATUS_ROUTES[app]
        try:
            answer = await client.call(
                client.guards.registry.get(route_id), path_params={param: approval_id}
            )
        except MiAssistError as error:
            return tool_error(deps, error)
        if isinstance(answer, Unavailable):
            return build(
                deps.guidance,
                tool="miassist_approval_status",
                outcome="unavailable",
                level=level,
                data=None,
                unavailable=app,
                reason=answer.reason,
            )
        if isinstance(answer, AppError):
            return tool_error(deps, MiAssistError(answer.code, answer.message or "the app refused"))
        if isinstance(answer, Pending):
            approval = answer.approval
        elif isinstance(answer, Resource):
            style: Style = "file_first" if app == "miworkbench" else "server_executed"
            try:
                approval = approval_object(
                    app,
                    answer.body,
                    style=style,
                    summary=deps.guidance.apps.apps[app].approvals_page,
                )
            except MiAssistError as error:
                return tool_error(deps, error)
        else:
            return tool_error(deps, MiAssistError("approval_unreadable", "unexpected answer"))
        return build(
            deps.guidance,
            tool="miassist_approval_status",
            outcome=approval["status"],
            level=level,
            data={"app": app, "approval_id": approval_id},
            approval=approval,
            terms=["approval"],
        )

    miassist_approval_status.__annotations__["app"] = Literal[installed] if installed else str
    miassist_approval_status.__annotations__["return"] = Result
    return miassist_approval_status


CORE_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("miassist_guide", "none", True, False, frozenset({"store_read"}), make_guide),
    ToolSpec("miassist_glossary", "none", True, False, frozenset({"store_read"}), make_glossary),
    ToolSpec("miassist_status", "none", True, False, frozenset({"store_read"}), make_status),
    ToolSpec(
        "miassist_set_guidance", "none", False, False, frozenset({"store_write"}), make_set_guidance
    ),
    ToolSpec(
        "miassist_reset_my_settings", "none", False, True, frozenset({"store_delete"}), make_reset
    ),
    ToolSpec(
        "miassist_overview",
        "any",
        True,
        False,
        frozenset({"store_read", "app_read"}),
        make_overview,
    ),
    ToolSpec(
        "miassist_approval_status",
        "any",
        True,
        False,
        frozenset({"store_read", "app_read"}),
        make_approval_status,
    ),
)
