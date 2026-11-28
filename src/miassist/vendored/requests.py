"""The request schemas Core's pre-filing check reads in production (001 FR-16 V-1; 003
OVN-miassist-pb003-1): ``miworkbench_request_schemas.json``, written by
``scripts/write_request_schemas.py`` from the committed snapshot. A route that is not in it gets
``None``, so Core files nothing for it (fail closed)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from miassist.adapters.base import AppClient, Route
from miassist.adapters.miworkbench import RequestSchema, WorkbenchAdapter


@cache
def _table() -> dict[str, Any]:
    raw = resources.files("miassist.vendored").joinpath("miworkbench_request_schemas.json")
    data: dict[str, Any] = json.loads(raw.read_text(encoding="utf-8"))["routes"]
    return data


def lookup(route: Route) -> RequestSchema | None:
    entry = _table().get(f"{route.method} {route.path}")
    if entry is None:
        return None
    return RequestSchema(query=frozenset(entry["query"]), body=entry["body"])


def refusals(route: Route, query: Mapping[str, Any], body: Any) -> list[str]:
    """Where a request departs from the route's own request schema (types, bounds, enums, required
    fields): what miWorkbench would refuse with a 422. Checked BEFORE an approval is filed, so the
    operator never approves a request the app then refuses after spending the approval (A40). R1
    review fix (OR1-pb-7), 2026-11-16. A route with no description is refused whole."""
    entry = _table().get(f"{route.method} {route.path}")
    if entry is None:
        return ["the route has no request description"]
    found: list[str] = []
    for name, value in query.items():
        schema = entry.get("query_schemas", {}).get(name)
        if schema is None:
            found.append(f"query.{name}: not declared")
            continue
        found += [
            f"query.{name}: {e.message}" for e in Draft202012Validator(schema).iter_errors(value)
        ]
    if entry.get("body") is not None and (body is not None or entry.get("body_required")):
        validator = Draft202012Validator(entry["body"])
        found += [
            f"body{''.join(f'.{p}' for p in e.absolute_path)}: {e.message}"
            for e in validator.iter_errors(body)
        ]
    return found


def workbench(client: AppClient) -> WorkbenchAdapter:
    """miWorkbench's file-first adapter over the production schema lookup."""
    return WorkbenchAdapter(client, lookup)
