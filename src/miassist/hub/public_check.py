"""The Hub check (001 FR-29; A17, A23, A37, R2M-16; FTID §3.12).

No route that touches the Hub for a caller-named repository is called before an EXACT-repository
public check passes: miDataworks' search for that id, then ``private: false`` and ``gated: false``
for the exact (case-sensitive) ``repo_id``; the size from the preview, only after the check. With
no miDataworks installed there is no check, and the import is the operator's step.

Only ``run_public_check`` makes a ``PublicCheck``. Nothing about the search's other items is
returned or logged. ``public_hub_search`` is the one copy of the private/gated drop: it returns the
public candidates and a COUNT of the dropped ones, never their names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from miassist.adapters.base import AppClient, Handoff, PublicCheck, Resource, issue_public_check

SEARCH_LIMIT = 20


@dataclass(frozen=True)
class HubCandidate:
    repo_id: str
    licence: str | None
    downloads: int | None


def _items(body: Any) -> list[Mapping[str, Any]]:
    if isinstance(body, Mapping):
        for key in ("items", "results", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, Mapping)]
    if isinstance(body, list):
        return [i for i in body if isinstance(i, Mapping)]
    return []


def _public(item: Mapping[str, Any]) -> bool:
    return item.get("private") is False and item.get("gated") is False


def _split_bytes(body: Any) -> int | None:
    if not isinstance(body, Mapping):
        return None
    splits = body.get("splits")
    if isinstance(splits, list):
        sizes = [s.get("bytes") for s in splits if isinstance(s, Mapping)]
        ints = [b for b in sizes if isinstance(b, int)]
        if sizes and len(ints) == len(sizes):
            return sum(ints)
    size = body.get("bytes", body.get("size_bytes"))
    return size if isinstance(size, int) else None


async def run_public_check(
    clients: Mapping[str, AppClient], repo_id: str, *, with_size: bool
) -> PublicCheck | Handoff | Resource:
    """A ``PublicCheck`` for exactly ``repo_id``; a ``Handoff`` when no check is possible; any
    other app answer (unavailable, an error) is returned unchanged for the caller to map."""
    dataworks = clients.get("midataworks")
    if dataworks is None:
        return Handoff("midataworks", "hf_import_by_operator")
    registry = dataworks.guards.registry
    found = await dataworks.call(
        registry.get("midataworks.hf_search"), json={"query": repo_id, "limit": SEARCH_LIMIT}
    )
    if not isinstance(found, Resource):
        return found  # type: ignore[return-value]
    item = next((i for i in _items(found.body) if i.get("repo_id") == repo_id), None)
    public = item is not None and _public(item)
    licence = item.get("licence") if item is not None else None
    check = issue_public_check(repo_id, public, None, licence if isinstance(licence, str) else None)
    if not public or not with_size:
        return check
    preview = await dataworks.call(
        registry.get("midataworks.hf_preview"), json={"repo_id": repo_id}, public_check=check
    )
    if not isinstance(preview, Resource):
        return preview  # type: ignore[return-value]
    preview_licence = preview.body.get("licence") if isinstance(preview.body, Mapping) else None
    return issue_public_check(
        repo_id,
        True,
        _split_bytes(preview.body),
        preview_licence if isinstance(preview_licence, str) else check.licence,
    )


async def public_hub_search(
    clients: Mapping[str, AppClient], query: str, limit: int, licences: list[str]
) -> tuple[list[HubCandidate], int] | Handoff | Resource:
    """Public candidates for ``query`` and the count of private or gated ones dropped."""
    dataworks = clients.get("midataworks")
    if dataworks is None:
        return Handoff("midataworks", "hf_import_by_operator")
    found = await dataworks.call(
        dataworks.guards.registry.get("midataworks.hf_search"),
        json={"query": query, "limit": limit, "licences": licences},
    )
    if not isinstance(found, Resource):
        return found  # type: ignore[return-value]
    items = _items(found.body)
    kept = [
        HubCandidate(
            str(i.get("repo_id")),
            i.get("licence") if isinstance(i.get("licence"), str) else None,
            i.get("downloads") if isinstance(i.get("downloads"), int) else None,
        )
        for i in items
        if _public(i)
    ]
    return kept, len(items) - len(kept)
