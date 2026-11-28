"""The floor's bounds (FPRD FR-30; A24, A37; FTID §3.11).

- ``FloorLimiter``: a sliding window per (budget, scope) in process memory, behind a lock. A route's
  budget is ``route.budget or route.floor_entry``. ``AppClient.call`` takes a slot IMMEDIATELY before
  sending, so a call refused for any other reason consumes none (A37). The counters live in this
  process, which is why the Deployment is pinned to one replica (ADR-003).
- ``PendingCap``: before a call that may file an approval, the app's pending list is read (paging to
  the route's maximum page) and the items filed by miAssist are counted; at the cap the call is
  refused ``too_many_pending``. The cap is shared by every caller (R3M-16).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from miassist.adapters.base import ProgrammingError, Resource
from miassist.errors import MiAssistError

if TYPE_CHECKING:
    from miassist.adapters.base import AppClient


@dataclass(frozen=True)
class Limit:
    """``count`` uses per ``window_s``; ``scoped``: counted per the caller-passed scope."""

    count: int
    window_s: int
    scoped: bool = False


_THIRTY = Limit(30, 3600)
#: One row per floor entry plus the two Hub budgets (A24, A37). Overrides never remove a row.
FLOOR_LIMITS: Final[Mapping[str, Limit]] = {
    "detector.create_behaviour": _THIRTY,
    "detector.register_views": _THIRTY,
    "detector.create_nonsense_text": _THIRTY,
    "steering.import_probe": _THIRTY,
    "dataset.create": _THIRTY,
    "dataset.save_recipe": _THIRTY,
    "dataset.build_version": _THIRTY,
    "dataset.build_files": _THIRTY,
    "steering.save_profile": _THIRTY,
    "steering.import_cluster": _THIRTY,
    "steering.import_circuit": _THIRTY,
    "steering.test_chat": Limit(1, 3600, scoped=True),
    "import.hf_miworkbench": Limit(5, 3600),
    "import.hf_midataworks": Limit(5, 3600),
    "hub.search": Limit(20, 3600),
    "hub.preview": Limit(20, 3600),
}


def limits_with_overrides(raw: str | None) -> dict[str, Limit]:
    """``FLOOR_LIMITS`` with ``MIASSIST_FLOOR_LIMITS`` (JSON ``{entry: {count, window_s}}``) applied.
    An unknown entry refuses start; a row can be changed, never removed."""
    limits = dict(FLOOR_LIMITS)
    if not raw:
        return limits
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("config_refused: MIASSIST_FLOOR_LIMITS must be a JSON object")
    for entry, value in data.items():
        if entry not in limits or not isinstance(value, dict):
            raise SystemExit(
                f"config_refused: MIASSIST_FLOOR_LIMITS names an unknown entry {entry!r}"
            )
        base = limits[entry]
        count = int(value.get("count", base.count))
        window = int(value.get("window_s", base.window_s))
        if count < 0 or window <= 0:
            raise SystemExit(f"config_refused: MIASSIST_FLOOR_LIMITS[{entry!r}] is out of range")
        limits[entry] = Limit(count, window, base.scoped)
    return limits


class FloorLimiter:
    """Sliding-window counts per (budget, scope)."""

    def __init__(
        self, limits: Mapping[str, Limit] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limits = dict(FLOOR_LIMITS if limits is None else limits)
        self._clock = clock
        self._uses: dict[tuple[str, str | None], deque[float]] = {}
        self._lock = asyncio.Lock()

    async def take(self, budget: str, scope: str | None) -> None:
        limit = self.limits.get(budget)
        if limit is None:
            raise ProgrammingError(f"no floor limit for {budget!r}")
        if limit.scoped and not scope:
            raise ProgrammingError(f"{budget} is counted per scope: pass floor_scope")
        key = (budget, scope if limit.scoped else None)
        async with self._lock:
            now = self._clock()
            uses = self._uses.setdefault(key, deque())
            while uses and now - uses[0] >= limit.window_s:
                uses.popleft()
            if len(uses) >= limit.count:
                raise MiAssistError(
                    "floor_limit",
                    "this kind of change has reached its limit for now",
                    fix=f"try again later; at most {limit.count} per {limit.window_s // 60} minutes",
                )
            uses.append(now)


#: The value each app records as miAssist's ``requested_by`` (ADR-006's table).
REQUESTED_BY: Final[Mapping[str, str]] = {
    "miworkbench": "miassist",
    "miserver": "agent:miassist",
    "midataworks": "agent:miassist",
    "miforge": "agent:miassist",
}
#: Each app's pending-list paging (from the snapshots): offset paging, or none (one full page).
_PAGING: Final[Mapping[str, str]] = {
    "miworkbench": "offset",
    "miserver": "offset",
    "midataworks": "offset",
    "miforge": "none",
}
MAX_PAGE: Final = 500


def approval_items(body: Any) -> list[dict[str, Any]] | None:
    """The approval items of a list answer, whichever envelope the app uses; ``None`` if unknown."""
    candidates: list[Any] = [body]
    if isinstance(body, dict):
        candidates += [body.get("approvals"), body.get("items"), body.get("data")]
        data = body.get("data")
        if isinstance(data, dict):
            candidates += [data.get("approvals"), data.get("items")]
    for candidate in candidates:
        if isinstance(candidate, list) and all(isinstance(i, dict) for i in candidate):
            return candidate
    return None


class PendingCap:
    """``too_many_pending`` at ``cap`` pending approvals filed by miAssist, per app (A24)."""

    def __init__(self, cap: int = 10) -> None:
        self.cap = cap

    async def check(self, app: str, client: AppClient) -> None:
        route = client.guards.registry.get(f"{app}.list_approvals")
        mine = 0
        offset = 0
        while True:
            params: dict[str, Any] = {"status": "pending", "limit": MAX_PAGE}
            if _PAGING[app] == "offset":
                params["offset"] = offset
            answer = await client.call(route, params=params)
            if not isinstance(answer, Resource):
                raise MiAssistError(
                    "pending_cap_unreadable",
                    f"miAssist could not read {app}'s pending approvals, so it files nothing now",
                    fix="try again when the app answers",
                )
            items = approval_items(answer.body)
            if items is None:
                raise MiAssistError(
                    "pending_cap_unreadable",
                    f"{app}'s approval list was not in a shape miAssist reads, so it files nothing",
                    fix="the app's version may differ from the one miAssist was built against",
                )
            mine += sum(
                1
                for item in items
                if item.get("requested_by") == REQUESTED_BY[app]
                and item.get("status", "pending") == "pending"
            )
            if mine >= self.cap:
                raise MiAssistError(
                    "too_many_pending",
                    f"{self.cap} requests from miAssist are already waiting in {app}",
                    fix="the operator decides them first, in the app's Approvals page",
                )
            if _PAGING[app] == "none" or len(items) < MAX_PAGE:
                return
            offset += len(items)
