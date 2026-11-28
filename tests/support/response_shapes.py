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

Since ENH-013 006, an app whose state is ``vendored`` (``answer_contracts.ANSWER_SOURCES``) answers
from its published answer contract instead, and from nothing else (``lookup``): MA4.

``check`` fails an answer that INVENTS a field (a key the shape does not declare in a closed object),
DROPS one (a required key absent), or carries a value of another type or outside an enum, or breaks
any other rule of the shape. Since 2026-11-25 it is ``jsonschema`` (Draft 2020-12) over the shape's
strict form, with ``$ref`` resolved through a ``referencing`` registry: the hand-written walk it
replaced followed no ``$ref`` and ignored ``if``/``then``, ``allOf`` and ``prefixItems`` (and every
bound and pattern), so an answer wrong at any of them passed. ``example`` builds the smallest answer
that passes, so a fake states only what a test needs on top of it.
"""

from __future__ import annotations

import json
import re
import reprlib
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from tests.support import answer_contracts

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


#: Where a shape came from: the app's vendored answer contract (``answer_contracts``, a
#: ``vendored`` app), a hand record in ``responses.json``, or the OpenAPI snapshot's model.
SOURCES = ("contract", "responses.json", "snapshot")


def lookup(app: str, method: str, template: str, status: int | str) -> tuple[str, Any | None]:
    """``(source, shape)`` of ``app``'s answer to ``method template`` with ``status``. A
    ``vendored`` app (ENH-013 006, MA4) answers from its contract only, its strict form inlined;
    the shape is None when the contract has no such answer or lists the route as ``excluded``, and
    a 4xx or 5xx is the route's own entry or else the contract's error envelope (FR-006.7).
    A ``hand`` app answers from ``responses.json``, else the snapshot's response model as SENT
    (``all_required``), else ``(snapshot, None)``."""
    if answer_contracts.vendored(app):
        if str(status).isdigit() and int(status) >= 400:
            return "contract", answer_contracts.refusal(app, method, template, status)
        return "contract", answer_contracts.resolved(app, method, template, status)
    entry = (
        vendored()["apps"]
        .get(app, {})
        .get("routes", {})
        .get(f"{method.upper()} {template}", {})
        .get(str(status))
    )
    if entry is not None:
        return "responses.json", entry["schema"]
    found = openapi_schema(app, method, template, status)
    return "snapshot", all_required(found) if concrete(found) else None


def schema_for(app: str, method: str, template: str, status: int | str) -> Any | None:
    """The shape of ``app``'s answer to ``method template`` with ``status``; None when nothing is
    vendored for it (a fake answering it is then inventing the answer)."""
    return lookup(app, method, template, status)[1]


def shape_source(app: str, method: str, template: str, status: int | str) -> str:
    """Which of ``SOURCES`` ``schema_for`` reads that answer from (FR-006.6's registry walk)."""
    return lookup(app, method, template, status)[0]


#: The base URI a shape without its own ``$id`` is registered under, so a ``$ref`` inside a part of
#: it (``check(part, value, root=shape)``) resolves against the whole shape.
BASE_URI = "urn:miassist:shape"

#: Keywords whose subschemas constrain the SAME value as the schema holding them, each only in
#: part (an ``if`` names ``action`` alone; a ``then`` names ``result`` alone; an ``allOf`` member
#: adds one rule). Closing one of them would refuse every key its siblings declare, so they stay
#: open; the object holding them is closed by its own ``properties``.
PARTIAL = frozenset({"if", "then", "else", "not", "allOf", "dependentSchemas"})
#: Keywords whose value is a map of name to subschema.
NAMED = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
#: Keywords whose value is data, never a subschema.
DATA = frozenset(
    {"enum", "const", "required", "default", "examples", "example", "discriminator", "x-source"}
)


def strict(schema: Any, base: str = BASE_URI, *, partial: bool = False) -> Any:
    """A copy of ``schema`` that is closed where ``check`` has always closed it: an object with
    ``properties`` and no ``additionalProperties`` refuses any other key; one whose
    ``additionalProperties`` is a schema (a map) or ``true`` stays open; ``required`` is the
    shape's own, never widened (``all_required`` makes a response model's, as before). Partial
    subschemas (``PARTIAL``) are not closed. A local ``$ref`` (``#/...``) is made absolute under
    ``base`` so it resolves from a part of the shape too."""
    if isinstance(schema, list):
        return [strict(s, base, partial=partial) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "$ref" and isinstance(value, str) and value.startswith("#"):
            out[key] = base + value
        elif key in DATA:
            out[key] = value
        elif key in NAMED and isinstance(value, dict):
            out[key] = {n: strict(s, base, partial=key in PARTIAL) for n, s in value.items()}
        elif key in PARTIAL:
            out[key] = strict(value, base, partial=True)
        else:
            out[key] = strict(value, base)
    if not partial and isinstance(out.get("properties"), dict):
        out.setdefault("additionalProperties", False)
    return out


def _integer(_: Any, value: Any) -> bool:
    """An ``int``, never a ``bool`` or a whole ``float`` (``1.0``): what ``check`` always held."""
    return isinstance(value, int) and not isinstance(value, bool)


_VALIDATOR = jsonschema.validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", _integer),
)


@cache
def _compiled(shape: str, root: str, resources: str) -> Any:
    """A validator for the strict form of ``shape``, with ``root`` (the whole shape) and each
    external document of ``resources`` in its ``referencing`` registry (JSON text keys: cached)."""
    whole = json.loads(root)
    base = str(whole.get("$id") or BASE_URI) if isinstance(whole, dict) else BASE_URI
    registry: Registry[Any] = Registry().with_resource(
        base, Resource.from_contents(strict(whole, base), default_specification=DRAFT202012)
    )
    for uri, document in json.loads(resources).items():
        registry = registry.with_resource(
            uri, Resource.from_contents(strict(document, uri), default_specification=DRAFT202012)
        )
    return _VALIDATOR(strict(json.loads(shape), base), registry=registry)


def _path(where: str, steps: Any) -> str:
    out = where
    for step in steps:
        out += f"[{step}]" if isinstance(step, int) else f".{step}"
    return out


#: At one place in a value and one node of the shape, the first of these that fails is the only
#: one reported, as ``check`` always did (a value of the wrong type is not also "too short").
_FIRST = ("anyOf", "oneOf", "enum", "const", "type")


def _kept(errors: list[ValidationError]) -> list[ValidationError]:
    groups: dict[tuple[Any, ...], list[ValidationError]] = {}
    for error in errors:
        node = (tuple(error.absolute_path), tuple(error.absolute_schema_path)[:-1])
        groups.setdefault(node, []).append(error)
    kept: list[ValidationError] = []
    for group in groups.values():
        first = [e for name in _FIRST for e in group if e.validator == name][:1]
        kept += first or group
    return kept


def _said(errors: list[ValidationError], where: str) -> list[str]:
    """Today's messages for jsonschema's errors: invented, dropped, a wrong type or enum value, no
    branch; any other rule (a bound, a pattern, a tuple's items) in jsonschema's own words."""
    found: list[str] = []
    for error in _kept(errors):
        at = _path(where, error.absolute_path)
        name, rule, value = error.validator, error.validator_value, error.instance
        if name in ("anyOf", "oneOf"):
            branches: dict[Any, list[ValidationError]] = {}
            for sub in error.context or []:
                branches.setdefault(sub.relative_schema_path[0], []).append(sub)
            if len(branches) < len(rule):
                found.append(f"{at}: matches more than one branch (the app sends one)")
                continue
            best = min((_said(subs, where) for subs in branches.values()), key=len)
            found.append(f"{at}: matches no branch ({best[0]})")
        elif name == "enum":
            found.append(f"{at}: {value!r} is not one of {rule}")
        elif name == "const":
            found.append(f"{at}: {value!r} is not {rule!r}")
        elif name == "type":
            kinds = rule if isinstance(rule, list) else [rule]
            found.append(f"{at}: {type(value).__name__} where the app sends {kinds}")
        elif name == "additionalProperties" and rule is False:
            props = error.schema.get("properties") or {}
            patterns = list(error.schema.get("patternProperties") or {})
            found += [
                f"{at}.{key}: invented (the app never sends it)"
                for key in value
                if key not in props and not any(re.search(p, key) for p in patterns)
            ]
        elif name == "required":
            found += [
                f"{at}.{key}: dropped (the app always sends it)" for key in rule if key not in value
            ]
        else:  # a bound, a pattern, a tuple's items: jsonschema's words, the value shortened
            found.append(f"{at}: {error.message.replace(repr(value), reprlib.repr(value))}")
    return list(dict.fromkeys(found))


def check(
    schema: Any,
    value: Any,
    where: str = "$",
    *,
    root: Any = None,
    resources: Mapping[str, Any] | None = None,
) -> list[str]:
    """Every way ``value`` departs from ``schema`` (empty: it is the app's shape).

    Validated by ``jsonschema`` (Draft 2020-12) against the shape's strict form (``strict``): every
    keyword counts, ``$ref`` (through a ``referencing`` registry over ``root``, the whole shape
    when ``schema`` is a part of it, and ``resources``, external documents by URI), ``if``/
    ``then``/``else``, ``allOf``, ``prefixItems``, bounds and patterns. Before 2026-11-25 a
    hand-written walk read only ``properties``, ``items``, ``anyOf``/``oneOf``, ``enum``, ``const``
    and ``type``, and passed any answer at a keyword it did not read. ``format`` is not asserted,
    as before."""
    if not isinstance(schema, Mapping) or not schema:
        return []
    texts = (
        json.dumps(schema),
        json.dumps(schema if root is None else root),
        json.dumps(dict(resources or {})),
    )
    try:
        errors = list(_compiled(*texts).iter_errors(value))
    except Unresolvable as exc:
        return [f"{where}: the shape's $ref does not resolve ({exc})"]
    return _said(errors, where)


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
