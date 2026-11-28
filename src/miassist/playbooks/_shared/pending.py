"""The repeat-call lookup of a playbook's own approval request (003 FTID §3.2; A18, A43, V-5,
R1M-14). ONE module for 003, 004 and 005 (R1 review fix OR1-pb-10, 2026-11-16; the merge contract is
in the 045 fixer's NEEDS.md).

Before a playbook files (or asks an app to file) an approval, it looks for its OWN request for the
same action and the same payload, so a repeated first call files nothing new:

- the id the caller remembers (its progress record), read directly; returned only while it still
  leads somewhere (``OPEN``, or ``CLOSED`` when the caller asks for closed outcomes) and only when it
  is miAssist's, for this action (OR1-pb-18: a ``consumed`` or foreign id is never returned);
- else each app's approval list, read with a ``status`` filter per status and filtered CLIENT-SIDE
  (no list route filters by requester) on ``requested_by`` as the app records it, the action, and
  the payload: its digest (the WHOLE filed payload, Core's ``canonical_payload`` with ``_method`` and
  ``_route`` for miWorkbench; V-5) or a field match. miWorkbench stores the payload verbatim; an app
  that stores the handler's arguments (miDataworks: the body under ``body``, with enrichment beside
  it, ``core/agent_origin.py:342-357``) is searched one level deep.

Statuses searched (``OPEN_STATUSES``): ``pending`` everywhere; ``approved`` on miWorkbench, whose
file-first approvals are approved and then used by the caller: an approved, unused request must be
found, or a repeat call files a second GPU approval while the first waits (OR1-pb-10a); and
``executing`` on miDataworks, miServer and miForge, which run an approved request themselves
(``pending -> executing -> executed``): while it runs, a repeat call must find it, not file a second
one (R2 review fix OR2-int-1, 2026-11-16). ``executed`` is never open: the request is done, and a
later need (a model unloaded since, a changed send) is a new request; a caller that reports a
finished outcome searches it itself (004's publish). Matches come newest first.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from typing import Any, Final

from miassist.adapters.base import AppClient, Resource
from miassist.adapters.limits import approval_items

#: What each app records as ``requested_by`` for miAssist (miWorkbench ``mcp_approvals.py:215-222``
#: stores the raw header value; miServer ``approval_gate.py:174-185``; miDataworks
#: ``agent_origin.py``).
REQUESTED_BY: Final[Mapping[str, str]] = {
    "miworkbench": "miassist",
    "midataworks": "agent:miassist",
    "miserver": "agent:miassist",
    "miforge": "agent:miassist",
}
#: The approval list and single-read routes, the field naming the action, the path parameter.
ROUTES: Final[Mapping[str, tuple[str, str, str, str]]] = {
    "miworkbench": (
        "miworkbench.list_approvals",
        "miworkbench.get_approval",
        "tool_name",
        "request_id",
    ),
    "midataworks": (
        "midataworks.list_approvals",
        "midataworks.get_approval",
        "action",
        "approval_id",
    ),
    "miserver": ("miserver.list_approvals", "miserver.get_approval", "action", "approval_id"),
    "miforge": ("miforge.list_approvals", "miforge.get_approval", "action", "approval_id"),
}
#: A request that still leads somewhere: waiting for the operator, (miWorkbench) approved and not
#: yet used, or (the server-executed apps) approved and running (R2 review fix OR2-int-1).
#: Each value is an approval ``status`` its app's answer contract declares: miServer's
#: ``docs/schemas/miserver-answers-v1.json#/$defs/ApprovalRead/properties/status`` (ENH-013 006;
#: ``tests/support/answer_enums.py``, the others as each app's <app>-answers-v1.json is vendored).
OPEN: Final = frozenset({"pending", "approved", "executing"})
#: A closed outcome for the same request: reported instead of filing again, unless the person asks
#: again (``ask_again`` skips the lookup; FR-003.22, FR-004.16). Pinned like ``OPEN``, to each
#: app's contract: miServer's ``docs/schemas/miserver-answers-v1.json`` approval ``status``.
CLOSED: Final = frozenset({"denied", "rejected", "expired", "failed"})
#: The list statuses searched for an open request, per app: each an approval ``status`` its app's
#: answer contract declares (miServer's ``docs/schemas/miserver-answers-v1.json``; ENH-013 006).
OPEN_STATUSES: Final[Mapping[str, tuple[str, ...]]] = {
    "miworkbench": ("pending", "approved"),
    "midataworks": ("pending", "executing"),
    "miserver": ("pending", "executing"),
    "miforge": ("pending", "executing"),
}
#: The closed statuses searched, per app, pinned like ``OPEN_STATUSES`` (miServer's
#: ``docs/schemas/miserver-answers-v1.json``).
CLOSED_STATUSES: Final[Mapping[str, tuple[str, ...]]] = {
    "miworkbench": ("denied", "expired", "failed"),
    "midataworks": ("rejected", "expired", "failed"),
    "miserver": ("rejected", "expired", "failed"),
    "miforge": ("rejected", "expired", "failed"),
}


def digest(payload: Any) -> str:
    """sha256 of the canonical JSON of ``payload`` (sorted keys, compact, UTF-8)."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_id(row: Mapping[str, Any]) -> str | None:
    """An approval row's id (miServer and the 202 answers name it ``approval_id``)."""
    value = row.get("id", row.get("approval_id"))
    return str(value) if value not in (None, "") else None


def _candidates(payload: Any) -> list[Mapping[str, Any]]:
    """The payload and, one level deep, each object inside it."""
    if not isinstance(payload, Mapping):
        return []
    return [payload, *(v for v in payload.values() if isinstance(v, Mapping))]


def _matches(
    payload: Any,
    payload_digest: str | None,
    fields: Mapping[str, Any] | None,
    keys: Collection[str] | None = None,
) -> bool:
    for candidate in _candidates(payload):
        seen = {k: candidate.get(k) for k in keys} if keys is not None else candidate
        if payload_digest is not None and digest(seen) == payload_digest:
            return True
        if fields and all(candidate.get(k) == v for k, v in fields.items()):
            return True
    return False


def _ours(app: str, row: Mapping[str, Any], action: str) -> bool:
    return row.get("requested_by") == REQUESTED_BY[app] and row.get(ROUTES[app][2]) == action


async def find_requests(
    client: AppClient,
    action: str,
    *,
    status: str,
    payload_digest: str | None = None,
    fields: Mapping[str, Any] | None = None,
    keys: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """This app's approvals in ``status`` filed by miAssist for ``action`` whose payload has
    ``payload_digest`` or carries every one of ``fields``; newest first. ``keys``: digest only
    those keys of each candidate (miDataworks fills defaults into the stored body, so 003's send
    digests the keys it sent; 003 FTID §3.2)."""
    if payload_digest is None and not fields:
        raise ValueError("find_requests needs a digest or fields to match on")
    app = client.app
    answer = await client.call(
        client.guards.registry.get(ROUTES[app][0]), params={"status": status}
    )
    if not isinstance(answer, Resource):
        return []
    found = [
        dict(item)
        for item in approval_items(answer.body) or []
        if item.get("status", status) == status
        and _ours(app, item, action)
        and _matches(item.get("payload"), payload_digest, fields, keys)
    ]
    found.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    return found


async def _remembered(
    client: AppClient, action: str, approval_id: str, statuses: frozenset[str]
) -> dict[str, Any] | None:
    app = client.app
    _, get_route, _, param = ROUTES[app]
    answer = await client.call(
        client.guards.registry.get(get_route), path_params={param: approval_id}
    )
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        return None
    row = answer.body
    if isinstance(row.get("data"), Mapping) and "success" in row:  # miServer's envelope
        row = row["data"]
    if row.get("status") in statuses and _ours(app, row, action):
        return dict(row)
    return None


async def open_request(
    client: AppClient,
    action: str,
    *,
    payload_digest: str | None = None,
    fields: Mapping[str, Any] | None = None,
    remembered: str | None = None,
    include_closed: bool = False,
    keys: Collection[str] | None = None,
) -> dict[str, Any] | None:
    """The approval row of THIS request (same action and payload) that still leads somewhere, or
    ``None`` (file a new one). ``include_closed`` also returns a closed outcome, so the caller
    reports it instead of filing again. An unreadable list answers ``None`` (Core's pending cap
    still applies when filing)."""
    app = client.app
    statuses = OPEN | (CLOSED if include_closed else frozenset())
    if remembered:
        row = await _remembered(client, action, remembered, statuses)
        if row is not None:
            return row
    searched = OPEN_STATUSES[app] + (CLOSED_STATUSES[app] if include_closed else ())
    for status in searched:
        found = await find_requests(
            client, action, status=status, payload_digest=payload_digest, fields=fields, keys=keys
        )
        if found:
            return found[0]
    return None


async def open_id(
    client: AppClient,
    action: str,
    *,
    payload_digest: str | None = None,
    fields: Mapping[str, Any] | None = None,
    remembered: str | None = None,
    include_closed: bool = False,
    keys: Collection[str] | None = None,
) -> str | None:
    """``open_request``'s id (003's callers take the id)."""
    row = await open_request(
        client,
        action,
        payload_digest=payload_digest,
        fields=fields,
        remembered=remembered,
        include_closed=include_closed,
        keys=keys,
    )
    return row_id(row) if row is not None else None
