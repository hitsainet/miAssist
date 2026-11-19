"""miWorkbench's adapter: file first (001 FR-16; A18, A29, A32, A38, A40; FTID §3.5).

miAssist NEVER calls a miWorkbench GPU route without an approved id, so a regression in the app's
own gate cannot start GPU work through miAssist:

1. **First call:** check the parts against the route's request schema (an undeclared key at any
   depth refuses ``invalid_arguments`` and files nothing; V-1), then file in miWorkbench's queue
   (``POST /api/v1/mcp/approvals``) with the route's action and the canonical payload. The GPU route
   receives nothing.
2. **Re-call with the id:** read the approval; unless it is ``approved`` return its status (no
   route call). The id must be for THIS route's action and filed by ``miassist`` (A18, R1M-29).
3. Call the route ONCE with the same parts and the id in ``X-MiStudio-Approval-Request``; the route
   consumes it. A non-2xx answer re-reads the status once (V-10): ``failed`` after the consume, or
   still ``approved``. ``failed`` is terminal: miAssist never re-files on it (A40).

``canonical_payload`` follows miWorkbench 045's rule (045 FTDD §16.3) and is public, so 003's and
005's repeat-call digests use the same form.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from miassist.adapters.base import (
    AppAnswer,
    AppClient,
    AppError,
    Pending,
    ProgrammingError,
    Resource,
    Route,
    issue_approved_id,
)
from miassist.errors import MiAssistError
from miassist.results.approvals import approval_object

REQUESTED_BY = "miassist"


def canonical_payload(
    method: str,
    route_template: str,
    path_params: Mapping[str, Any],
    query: Mapping[str, Any],
    body: Any,
    *,
    body_param: str | None = None,
) -> dict[str, Any]:
    """045's one flat rule: ``_method`` and ``_route`` (A38), the path parameters, the query, then the
    body's keys flat (a list body keyed by ``body_param``); ``approval_request_id`` dropped."""
    out: dict[str, Any] = {"_method": method.upper(), "_route": route_template}
    out.update(path_params)
    out.update(query)
    if isinstance(body, Mapping):
        out.update(body)
    elif body is not None:
        if not body_param:
            raise ProgrammingError("a non-object body needs its body_param (the handler's name)")
        out[body_param] = body
    out.pop("approval_request_id", None)
    return out


def _closed(schema: Mapping[str, Any]) -> bool:
    extra = schema.get("additionalProperties")
    return "properties" in schema and not extra


def _fits(value: Any, schema: Mapping[str, Any]) -> bool:
    """Whether ``value``'s JSON type is one ``schema`` allows (a branch of another type is not a
    candidate: an object never passes because an array branch declares nothing)."""
    kind = schema.get("type")
    if kind is None:
        return "properties" in schema if isinstance(value, Mapping) else "properties" not in schema
    kinds = kind if isinstance(kind, list) else [kind]
    if isinstance(value, Mapping):
        return "object" in kinds
    if isinstance(value, list):
        return "array" in kinds
    return not ({"object", "array"} >= set(kinds))


def undeclared_keys(value: Any, schema: Mapping[str, Any] | None, where: str = "body") -> list[str]:
    """Keys in ``value`` that ``schema`` does not declare, at any depth (V-1). A mapping-typed field
    (``additionalProperties`` given, L-9) is open."""
    if schema is None:
        return []
    for key in ("anyOf", "oneOf"):
        if key in schema:
            branches = [b for b in schema[key] if isinstance(b, Mapping) and _fits(value, b)]
            results = [undeclared_keys(value, b, where) for b in branches]
            return [] if any(not r for r in results) else results[0] if results else []
    if isinstance(value, Mapping):
        props = schema.get("properties", {})
        found: list[str] = []
        for key, item in value.items():
            if key in props:
                found += undeclared_keys(item, props[key], f"{where}.{key}")
            elif _closed(schema):
                found.append(f"{where}.{key}")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                found += undeclared_keys(item, schema["additionalProperties"], f"{where}.{key}")
        return found
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        return [
            k
            for i, item in enumerate(value)
            for k in undeclared_keys(item, schema["items"], f"{where}[{i}]")
        ]
    return []


@dataclass(frozen=True)
class RequestSchema:
    """A route's declared query names and body schema (from the snapshot; resolved)."""

    query: frozenset[str]
    body: Mapping[str, Any] | None


SchemaLookup = Callable[[Route], RequestSchema | None]


class WorkbenchAdapter:
    """File-first calls to miWorkbench's caller-executed GPU routes."""

    def __init__(self, client: AppClient, schemas: SchemaLookup) -> None:
        if client.app != "miworkbench":
            raise ProgrammingError("WorkbenchAdapter wraps miWorkbench's client")
        self.client = client
        self._schemas = schemas

    def _route(self, route_id: str) -> Route:
        return self.client.guards.registry.get(route_id)

    def _check_parts(self, route: Route, query: Mapping[str, Any], body: Any) -> None:
        schema = self._schemas(route)
        if schema is None:
            raise MiAssistError(
                "invalid_arguments",
                "miAssist has no request description for this route, so it files nothing",
                fix="this needs a miAssist update that pins the route's request schema",
            )
        unknown = [f"query.{k}" for k in query if k not in schema.query]
        unknown += undeclared_keys(body, schema.body)
        if unknown:
            raise MiAssistError(
                "invalid_arguments",
                f"the route does not declare {', '.join(sorted(unknown))}",
                fix="leave out what the route does not take; nothing was filed",
            )

    async def _status(self, approval_id: str) -> AppAnswer:
        return await self.client.call(
            self._route("miworkbench.get_approval"), path_params={"request_id": approval_id}
        )

    async def file_first(
        self,
        route: Route,
        *,
        path_params: Mapping[str, Any],
        query: Mapping[str, Any],
        body: Any,
        body_param: str | None = None,
        approval_id: str | None = None,
        person_reason: str | None = None,
        tool: str,
        args: Mapping[str, Any],
        summary: str,
        forecast: Mapping[str, Any] | None = None,
    ) -> AppAnswer:
        if not (route.file_first and route.approval_action):
            raise ProgrammingError(f"{route.id} is not a file-first route")
        canonical = canonical_payload(
            route.method, route.path, path_params, query, body, body_param=body_param
        )
        if approval_id is None:
            self._check_parts(route, query, body)
            filing: dict[str, Any] = {"tool_name": route.approval_action, "payload": canonical}
            if forecast:
                filing["forecast"] = dict(forecast)
            filed = await self.client.call(
                self._route("miworkbench.file_approval"), json=filing, person_reason=person_reason
            )
            if not isinstance(filed, Resource):
                return filed
            filed_id = filed.body.get("id") if isinstance(filed.body, Mapping) else None
            if not filed_id:
                raise MiAssistError("approval_unreadable", "miWorkbench filed no approval id")
            again = {"tool": tool, "args": {**args, "approval_id": str(filed_id)}}
            return Pending(
                "miworkbench",
                approval_object(
                    "miworkbench",
                    {**filed.body, "status": "pending", "tool_name": route.approval_action},
                    style="file_first",
                    summary=summary,
                    call_again_with=again,
                ),
            )
        state_answer = await self._status(approval_id)
        if not isinstance(state_answer, Resource):
            return self._not_found(state_answer)
        state = state_answer.body if isinstance(state_answer.body, Mapping) else {}
        if state.get("status") != "approved":
            return self._as_status(state, summary)
        if (
            state.get("tool_name") != route.approval_action
            or state.get("requested_by") != REQUESTED_BY
        ):
            raise MiAssistError(
                "approval_mismatch",
                "that approval was filed for another action or by another caller",
                fix="start again without an approval id; miAssist files a new request",
            )
        answer = await self.client.call(
            route,
            path_params=path_params,
            params=query,
            json=body,
            approval_id=issue_approved_id(approval_id, state),
            person_reason=person_reason,
        )
        if isinstance(answer, AppError):
            return await self._after_refusal(approval_id, answer, summary)
        return answer

    def _not_found(self, answer: AppAnswer) -> AppAnswer:
        if isinstance(answer, AppError) and answer.status == 404:
            raise MiAssistError(
                "approval_not_found",
                "miWorkbench has no approval with that id",
                fix="start again without an approval id",
            )
        return answer

    def _as_status(self, state: Mapping[str, Any], summary: str) -> Pending:
        return Pending(
            "miworkbench",
            approval_object("miworkbench", state, style="file_first", summary=summary),
        )

    async def _after_refusal(self, approval_id: str, answer: AppError, summary: str) -> AppAnswer:
        """The route refused. Re-read the status exactly once (V-10): ``failed`` (the handler
        refused after the consume, A40) is terminal; ``denied``/``expired`` map to their status;
        otherwise the route's own code decides (L-8)."""
        reread = await self._status(approval_id)
        if isinstance(reread, Resource) and isinstance(reread.body, Mapping):
            status = reread.body.get("status")
            if status in ("failed", "denied", "expired"):
                pending = self._as_status(reread.body, summary)
                if status == "failed" and not pending.approval.get("reason"):
                    pending.approval["reason"] = answer.message or None
                return pending
        code = answer.code.removeprefix("miworkbench.")
        if answer.status == 409 and code == "consumed":
            raise MiAssistError(
                "approval_spent", "that approval was already used", fix="start again without an id"
            )
        if answer.status == 404:
            raise MiAssistError("approval_not_found", "miWorkbench has no approval with that id")
        if answer.status == 422 and code == "mismatch":
            raise MiAssistError(
                "approval_mismatch", "the call does not match what was approved", fix="start again"
            )
        return answer
