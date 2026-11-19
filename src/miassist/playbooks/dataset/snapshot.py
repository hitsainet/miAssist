"""``read``: one dataset's state in miDataworks (004 FTDD §6 ``snapshot.py``; FTID §13).

Reads only (GETs and the approval list); never a write. A dataset is found by id, else by exact
name through ``GET /api/v1/datasets?q=`` (one page, ``limit`` 50). The status provider derives from
this alone, so deleting a progress record changes nothing (FR-004.19).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from miassist.adapters import dataset as dw
from miassist.adapters.base import AppClient, AppError, Resource, Route, Unavailable
from miassist.errors import MiAssistError
from miassist.playbooks._shared import pending

PAGE = 50


class Down(Exception):
    """miDataworks did not answer (``unavailable``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class DatasetSnapshot:
    dataset: dict[str, Any] | None = None
    version: dict[str, Any] | None = None
    publishes: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] | None = None  # the newest hub_push approval for the version


async def get(client: AppClient, route: Route | str, **kw: Any) -> Any | None:
    """A read's body; ``None`` on 404; ``Down`` when the app is unavailable; else the app's error."""
    target = client.guards.registry.get(route) if isinstance(route, str) else route
    answer = await client.call(target, **kw)
    if isinstance(answer, Resource):
        return answer.body
    if isinstance(answer, Unavailable):
        raise Down(answer.reason)
    if isinstance(answer, AppError):
        if answer.status == 404:
            return None
        raise MiAssistError(answer.code, answer.message or answer.code)
    return None


def items(body: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [i for i in body if isinstance(i, dict)]
    if isinstance(body, Mapping):
        for key in (*keys, "items", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
    return []


async def find_dataset(client: AppClient, ref: str) -> dict[str, Any] | None:
    """By id, else by exact name (miDataworks names are unique)."""
    listed = await get(client, dw.CORE_LIST_DATASETS, params={"q": ref, "page": 1, "limit": PAGE})
    for item in items(listed):
        if item.get("name") == ref or item.get("id") == ref:
            return item
    body = await get(client, dw.DATASET, path_params={"dataset_id": ref})
    return body if isinstance(body, dict) else None


async def find_version(
    client: AppClient, dataset: Mapping[str, Any], ref: str | None
) -> dict[str, Any] | None:
    version_id = ref or dataset.get("head_version_id")
    if not version_id:
        return None
    if ref is not None and ref.isdigit():
        full = await get(client, dw.DATASET, path_params={"dataset_id": dataset["id"]})
        for summary in items(full, "version_list"):
            if str(summary.get("number")) == ref:
                version_id = summary.get("id")
                break
    body = await get(client, dw.VERSION, path_params={"version_id": version_id})
    if not isinstance(body, dict):
        return None
    # R3 review fix (OR3-int-6), 2026-11-16: a version id from another dataset is not this
    # dataset's version (check and publish name both); it is treated as not found.
    if body.get("dataset_id") != dataset.get("id"):
        return None
    return body


async def publishes_for(client: AppClient, version_id: str) -> list[dict[str, Any]]:
    body = await get(
        client, dw.PUBLISHES_LIST, params={"version_id": version_id, "page": 1, "limit": PAGE}
    )
    return items(body, "publishes")


async def hub_push_approval(client: AppClient, version_id: str) -> dict[str, Any] | None:
    """The newest hub_push approval miAssist filed for this version, in any status."""
    found: list[dict[str, Any]] = []
    for status in ("pending", "executing", "executed", "failed", "rejected", "expired"):
        found += await pending.find_requests(
            client, "hub_push", status=status, fields={"version_id": version_id}
        )
    found.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    return found[0] if found else None


async def read(
    client: AppClient, dataset_ref: str, version_ref: str | None = None
) -> DatasetSnapshot:
    snap = DatasetSnapshot()
    snap.dataset = await find_dataset(client, dataset_ref)
    if snap.dataset is None:
        return snap
    snap.version = await find_version(client, snap.dataset, version_ref)
    if snap.version is None:
        return snap
    snap.publishes = await publishes_for(client, str(snap.version["id"]))
    snap.approval = await hub_push_approval(client, str(snap.version["id"]))
    return snap
