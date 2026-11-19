"""The pre-run fairness check (FR-002.14d; FTID §3.17): the goal behaviour does not exist before a
live run. Reads the goal's lists DIRECTLY from the apps (no recorder, no server under test, no
model), follows pagination, skips archived items, and matches names, keys and descriptions against
the goal's terms (case-insensitive, whole words) and against ids earlier runs of the goal created.
Its output names items for the operator, never for an agent.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from miassist_eval import classes
from miassist_eval.classes import Refusal

#: ``(app, route, page_token) -> (answer body, next page token or None)``.
Fetch = Callable[[str, str, str | None], Awaitable[tuple[Any, str | None]]]
TEXT_FIELDS = ("name", "key", "description", "title", "behaviour", "label")
WHERE = {
    "miworkbench": "miWorkbench (archive or delete it in its own page)",
    "miserver": "miServer (delete it in its Probes or Steering page)",
    "midataworks": "miDataworks (archive it in its own page)",
    "miforge": "miForge (archive it in its own page)",
}


@dataclass(frozen=True)
class Match:
    app: str
    route: str
    item_id: str
    text: str
    why: str

    def line(self) -> str:
        return (
            f"{self.app} {self.route}: {self.item_id} {self.text!r} ({self.why}); {WHERE[self.app]}"
        )


def archived(item: Mapping[str, Any]) -> bool:
    """Each app's archived flag (FTASKS 1.5 confirms them live): ``archived`` true,
    ``archived_at`` set, or a state or status of ``archived``/``deleted``."""
    if item.get("archived") is True or item.get("archived_at"):
        return True
    return str(item.get("state") or item.get("status") or "").lower() in {"archived", "deleted"}


def _items(body: Any) -> list[Mapping[str, Any]]:
    if isinstance(body, list):
        return [i for i in body if isinstance(i, Mapping)]
    if isinstance(body, Mapping):
        for key in (
            "items",
            "data",
            "results",
            "datasets",
            "behaviours",
            "probes",
            "clusters",
            "runs",
            "versions",
            "recipes",
        ):
            if key in body:
                return _items(body[key])
        for value in body.values():
            if isinstance(value, list) and any(isinstance(i, Mapping) for i in value):
                return _items(value)
    return []


def term_patterns(terms: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in terms]


def match_items(
    app: str,
    route: str,
    items: Iterable[Mapping[str, Any]],
    terms: Iterable[str],
    earlier_ids: set[str],
) -> list[Match]:
    pats = term_patterns(terms)
    out: list[Match] = []
    for item in items:
        if archived(item):
            continue
        item_id = str(item.get("id") or item.get("key") or item.get("name") or "?")
        if item_id in earlier_ids:
            out.append(
                Match(
                    app,
                    route,
                    item_id,
                    str(item.get("name", "")),
                    "created by an earlier run of this goal",
                )
            )
            continue
        for field in TEXT_FIELDS:
            value = item.get(field)
            if isinstance(value, str) and any(p.search(value) for p in pats):
                out.append(
                    Match(app, route, item_id, value, f"its {field} names the goal behaviour")
                )
                break
    return out


async def check(
    goal: Mapping[str, Any], fetch: Fetch, earlier_ids: set[str] | None = None, max_pages: int = 50
) -> dict[str, Any]:
    """The fairness block for the take's manifest; refuses ``fairness_precondition`` on a match."""
    earlier = earlier_ids or set()
    matches: list[Match] = []
    lists_read = []
    for entry in goal["fairness"]["lists"]:
        app, route = entry["app"], entry["route"]
        page: str | None = None
        pages = 0
        while True:
            body, page = await fetch(app, route, page)
            matches += match_items(app, route, _items(body), goal["fairness"]["terms"], earlier)
            pages += 1
            if not page or pages >= max_pages:
                break
        lists_read.append(f"{app} {route}")
    block = {
        "checked_utc": datetime.now(UTC).isoformat(),
        "lists_read": lists_read,
        "matches": [m.line() for m in matches],
        "passed": not matches,
    }
    if matches:
        raise Refusal(classes.FAIRNESS_PRECONDITION, "; ".join(m.line() for m in matches))
    return block
