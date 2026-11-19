"""The apps' real response shapes, for honest fakes (R1 review fix OR1-pb-6 to OR1-pb-9, 2026-11-16).

The playbooks were tested only against hand-written fakes whose answers the real apps never return
(review round 1, OVN-17): the playbook agreed with its fake by construction. Every answer a checked
fake gives is now validated against the app's own shape, read from the app's code at a recorded
commit:

- ``tests/fixtures/openapi/<app>.json``: the response schema of a route whose OpenAPI response is a
  concrete model (written by ``scripts/snapshot_openapi.py``). A Pydantic response model serialises
  every field, so every property is required and the object is closed.
- ``tests/fixtures/openapi/responses.json``: the hand-derived shape of a route whose OpenAPI response
  is open (a ``dict``, ``Any``), and of the error answers a fake gives; each entry cites its source
  lines. It wins over the snapshot, and must name the snapshot's top-level fields where the snapshot
  has them (``tests/contract/test_response_shapes.py``).

``check`` fails an answer that INVENTS a field (a key the shape does not declare in a closed object),
DROPS one (a required key absent), or carries a value of another type or outside an enum. ``example``
builds the smallest answer that passes, so a fake states only what a test needs on top of it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"


@cache
def vendored() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((OPENAPI / "responses.json").read_text())
    return data


@cache
def snapshot(app: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((OPENAPI / f"{app}.json").read_text())
    return data


def all_required(schema: Any) -> Any:
    """A response model's schema as it is SENT: every property present, the object closed."""
    if isinstance(schema, dict):
        out = {k: all_required(v) for k, v in schema.items()}
        if isinstance(out.get("properties"), dict):
            out["required"] = sorted(out["properties"])
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(schema, list):
        return [all_required(v) for v in schema]
    return schema


def concrete(schema: Any) -> bool:
    """True when the schema names fields (an object with properties, or a list of such)."""
    if not isinstance(schema, Mapping):
        return False
    if isinstance(schema.get("properties"), Mapping) and schema["properties"]:
        return True
    if isinstance(schema.get("items"), Mapping):
        return concrete(schema["items"])
    return any(concrete(b) for b in schema.get("anyOf", []) if isinstance(b, Mapping))


def openapi_schema(app: str, method: str, template: str, status: int | str) -> Any:
    op = snapshot(app).get("paths", {}).get(template, {}).get(method.lower(), {})
    response = op.get("responses", {}).get(str(status), {})
    return (response.get("content") or {}).get("application/json", {}).get("schema")


def schema_for(app: str, method: str, template: str, status: int | str) -> Any | None:
    """The shape of ``app``'s answer to ``method template`` with ``status``; None when nothing is
    vendored for it (a fake answering it is then inventing the answer)."""
    entry = (
        vendored()["apps"]
        .get(app, {})
        .get("routes", {})
        .get(f"{method.upper()} {template}", {})
        .get(str(status))
    )
    if entry is not None:
        return entry["schema"]
    found = openapi_schema(app, method, template, status)
    return all_required(found) if concrete(found) else None


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _type_ok(kind: str, value: Any) -> bool:
    if kind == "null":
        return value is None
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES.get(kind, (object,)))


def check(schema: Any, value: Any, where: str = "$") -> list[str]:
    """Every way ``value`` departs from ``schema`` (empty: it is the app's shape)."""
    if not isinstance(schema, Mapping) or not schema:
        return []
    for key in ("anyOf", "oneOf"):
        if key in schema:
            results = [check(b, value, where) for b in schema[key]]
            if any(not r for r in results):
                return []
            best = min(results, key=len)
            return [f"{where}: matches no branch ({best[0]})"]
    found: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {value!r} is not one of {schema['enum']}"]
    if "const" in schema and value != schema["const"]:
        return [f"{where}: {value!r} is not {schema['const']!r}"]
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_type_ok(k, value) for k in kinds):
            return [f"{where}: {type(value).__name__} where the app sends {kinds}"]
    if isinstance(value, Mapping):
        props = schema.get("properties")
        extra = schema.get("additionalProperties", props is None)
        for key, item in value.items():
            if isinstance(props, Mapping) and key in props:
                found += check(props[key], item, f"{where}.{key}")
            elif extra is False:
                found.append(f"{where}.{key}: invented (the app never sends it)")
            elif isinstance(extra, Mapping):
                found += check(extra, item, f"{where}.{key}")
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{where}.{key}: dropped (the app always sends it)")
    elif isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for i, item in enumerate(value):
            found += check(schema["items"], item, f"{where}[{i}]")
    return found


def example(schema: Any) -> Any:
    """The smallest value of ``schema``: required keys only, nulls where allowed, empty lists."""
    if not isinstance(schema, Mapping) or not schema:
        return None
    for key in ("anyOf", "oneOf"):
        if key in schema:
            branches = [b for b in schema[key] if isinstance(b, Mapping)]
            if any(b.get("type") == "null" for b in branches):
                return None
            return example(branches[0]) if branches else None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds] if kinds else []
    if "null" in kinds:
        return None
    kind = kinds[0] if kinds else ("object" if "properties" in schema else None)
    if kind == "object":
        props = schema.get("properties") or {}
        return {k: example(props.get(k)) for k in schema.get("required", [])}
    return {"array": [], "string": "evalfx", "integer": 0, "number": 0.0, "boolean": False}.get(
        str(kind)
    )


def fill(schema: Any, partial: Any) -> Any:
    """``partial`` with every field the app always sends added (``example`` values), at every depth.
    Nothing is removed: a key the app never sends stays, so ``check`` still reports it."""
    if not isinstance(schema, Mapping) or not schema:
        return partial
    for key in ("anyOf", "oneOf"):
        if key in schema:
            if partial is None:
                return None
            branches = [b for b in schema[key] if isinstance(b, Mapping)]
            filled = [fill(b, partial) for b in branches]
            for value, branch in zip(filled, branches, strict=True):
                if not check(branch, value):
                    return value
            for value, branch in zip(filled, branches, strict=True):
                if branch.get("type") != "null" and branch:
                    return value
            return partial
    if isinstance(partial, Mapping) and isinstance(schema.get("properties"), Mapping):
        props = schema["properties"]
        out = dict(partial)
        for key in schema.get("required", []):
            if key not in out:
                out[key] = example(props.get(key))
        return {k: fill(props[k], v) if k in props else v for k, v in out.items()}
    if isinstance(partial, list) and isinstance(schema.get("items"), Mapping):
        return [fill(schema["items"], item) for item in partial]
    return partial


def at(schema: Any, *path: str) -> Any:
    """The sub-schema at ``path`` (property names; ``[]`` for list items), through the first
    object branch of an ``anyOf``."""
    node = schema
    for step in path:
        if isinstance(node, Mapping) and "anyOf" in node:
            node = next(b for b in node["anyOf"] if concrete(b) or b.get("type") == "object")
        node = node["items"] if step == "[]" else node["properties"][step]
    return node


def shaped(app: str, route: str, status: int = 200, *path: str, **values: Any) -> Any:
    """An answer of ``app`` to ``route`` ("METHOD /template") with ``status``, or the part of it at
    ``path``: the smallest real answer with ``values`` set on top."""
    method, template = route.split(" ", 1)
    schema = schema_for(app, method, template, status)
    if schema is None:
        raise KeyError(f"no vendored shape for {app} {route} {status}")
    base = example(at(schema, *path))
    if isinstance(base, dict):
        return {**base, **values}
    return values or base
