"""A thin wrapper over Core's fixture-filter module (FR-002.14b, FR-002.14c; FTID §3.16; A37, R2M-7).

Every rule is Core's: ``AllowedSet``, ``filter_list`` and ``final_scan`` ARE Core's objects (the
identity is asserted by ``tests/unit/test_id_filter_vectors.py``, R3M-13). This module only adapts
002's route profiles (``ids``, ``creates``, ``list``) to Core's calls, rewrites a list's count fields
after Core's filter, keeps the Hugging Face search's public items (``keep_if``, A23) and finds a list
the profile does not cover (fail closed, ``unfiltered_list``). It adds no field rule.

If Core's module cannot be imported, ``CORE`` is None: ``record`` and ``gap-record`` refuse with
``filter_module_missing`` whatever ``MIASSIST_REQUIRE_CORE`` says (R3M-4); there is no fallback.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import re
from collections.abc import Mapping
from types import ModuleType
from typing import Any

from miassist_eval import classes

CORE_MODULE = "miassist_fixtures.filter"


def _import_core() -> ModuleType | None:
    try:
        return importlib.import_module(CORE_MODULE)
    except ImportError:
        return None


CORE = _import_core()


def require_core() -> ModuleType:
    """Core's module, or ``filter_module_missing`` (exit 2, zero runs)."""
    if CORE is None:
        raise classes.Refusal(classes.FILTER_MODULE_MISSING, CORE_MODULE)
    return CORE


if CORE is not None:
    AllowedSet = CORE.AllowedSet
    filter_list = CORE.filter_list
    final_scan = CORE.final_scan
    FixtureRefused = CORE.FixtureRefused
    RouteProfile = CORE.RouteProfile


class UnfilteredList(Exception):
    """An answer holding an array of objects on a route its profile does not cover."""


def has_object_array(body: Any) -> bool:
    """An array of objects at the top or one field deep (FTID §3.16)."""
    if isinstance(body, list):
        return any(isinstance(i, Mapping) for i in body)
    if isinstance(body, Mapping):
        return any(
            isinstance(v, list) and any(isinstance(i, Mapping) for i in v) for v in body.values()
        ) or any(
            isinstance(v, Mapping)
            and any(
                isinstance(w, list) and any(isinstance(i, Mapping) for i in w) for w in v.values()
            )
            for v in body.values()
        )
    return False


def core_profile(entry: Mapping[str, Any] | None, template: str) -> Any:
    """Core's ``RouteProfile`` for a route: its template, ``creates`` and the profile's ``ids``."""
    core = require_core()
    entry = entry or {}
    extra = frozenset(str(f).split(".")[-1] for f in entry.get("ids", []))
    return core.RouteProfile(template, creates=bool(entry.get("creates")), fields=extra)


def _get(body: Any, dotted: str) -> Any:
    node = body
    for part in [p for p in dotted.split(".") if p]:
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def _set(body: Any, dotted: str, value: Any) -> None:
    parts = [p for p in dotted.split(".") if p]
    node = body
    for part in parts[:-1]:
        if not isinstance(node, Mapping):
            return
        node = node.get(part)
    if isinstance(node, dict) and parts and parts[-1] in node:
        node[parts[-1]] = value


def filter_answer(entry: Mapping[str, Any] | None, body: Any, allowed: Any) -> tuple[Any, int]:
    """Core's ``filter_list`` per the route's ``list`` entry; ``(body, dropped)``.

    ``list: none`` passes the body unchanged. No entry and an array of objects raises
    ``UnfilteredList``. ``keep_if`` NARROWS Core's verdict (OVN-miassist-eval-6): an item survives
    only when Core keeps it AND it meets ``keep_if`` (A23's public, ungated Hugging Face results), so
    the take still passes Core's ``final_scan``. ``counts`` are rewritten by the number dropped.
    """
    core = require_core()
    spec = (entry or {}).get("list")
    if spec == "none":
        return body, 0
    if spec is None:
        if has_object_array(body):
            raise UnfilteredList("an array of objects on a route with no list entry")
        return body, 0
    items_path = str(spec.get("items", ""))
    whole = items_path in ("", "*")
    before = body if whole else _get(body, items_path)
    filtered = core.filter_list(body, allowed)
    after = filtered if whole else _get(filtered, items_path)
    keep_if = spec.get("keep_if")
    if keep_if and isinstance(after, list):
        narrowed = [
            i
            for i in after
            if isinstance(i, Mapping) and all(i.get(k) == v for k, v in keep_if.items())
        ]
        if whole:
            filtered = narrowed
        else:
            _set(filtered, items_path, narrowed)
        after = narrowed
    dropped = (
        (len(before) - len(after)) if isinstance(before, list) and isinstance(after, list) else 0
    )
    for count in spec.get("counts", []):
        value = _get(filtered, count)
        if isinstance(value, int) and not isinstance(value, bool):
            _set(filtered, count, max(0, value - dropped))
    return filtered, dropped


# ------------------------------------------------------------------ R1 review fix (OR1-002-7)
#: A run of base64 characters (standard and URL-safe alphabets) long enough to carry an id.
_B64_RUN = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
_MAX_DEPTH = 4
_MAX_TRIES = 512
EMBEDDED = "__embedded__"


def _b64_candidates(text: str) -> list[str]:
    """Every decoding of every base64 run in ``text``, at each of the four alignments, in both
    alphabets: base64 embedded at any offset decodes at one of them."""
    out = []
    for run in _B64_RUN.findall(text):
        run = run.rstrip("=").replace("-", "+").replace("_", "/")
        for offset in range(4):
            chunk = run[offset:]
            chunk = chunk[: len(chunk) - (len(chunk) % 4 == 1)]
            try:
                raw = base64.b64decode(chunk + "=" * (-len(chunk) % 4), validate=True)
                out.append(raw.decode("utf-8"))
            except (binascii.Error, ValueError):
                continue
    return out


def _embedded(text: str, depth: int) -> list[Any]:
    """The JSON objects or arrays ``text`` carries: at any offset, or inside base64 at any offset."""
    if depth >= _MAX_DEPTH:
        return []
    found: list[Any] = []
    decoder = json.JSONDecoder()
    tries = 0
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        tries += 1
        if tries > _MAX_TRIES:
            break
        try:
            obj, _ = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, (dict, list)) and obj:
            found.append(expand(obj, depth + 1))
    for decoded in _b64_candidates(text):
        found.extend(_embedded(decoded, depth + 1))
    return found


def expand(node: Any, depth: int = 0) -> Any:
    """A SCAN VIEW of ``node`` (never written or sent): beside every string that carries JSON or
    base64 at any offset, what it carries, under ``<key>.__embedded__``, so Core's rule sees the ids
    inside it. It adds no field rule (A22, R2M-7): Core's ``final_scan`` still decides."""
    if isinstance(node, Mapping):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out[str(key)] = expand(value, depth)
            if isinstance(value, str):
                inner = _embedded(value, depth)
                if inner:
                    out[f"{key}.{EMBEDDED}"] = inner
        return out
    if isinstance(node, list):
        items = [expand(v, depth) for v in node]
        extra = [
            {EMBEDDED: inner} for v in node if isinstance(v, str) and (inner := _embedded(v, depth))
        ]
        return items + extra
    if isinstance(node, str):
        inner = _embedded(node, depth)
        return {EMBEDDED: inner, "text": node} if inner else node
    return node


def answer_findings(body: Any, allowed_set: Any) -> list[str]:
    """Core's ``final_scan`` over one answer's scan view: every value in it that is not fixture data
    (R1 review fix OR1-002-2: refused at the recorder, never recorded or passed on)."""
    core = require_core()
    doc = {"records": [{"seq": 0, "request": {}, "answer": {"body": expand(body)}}]}
    found: list[str] = core.final_scan(doc, allowed_set)
    return found


def take_findings(cassette_doc: Mapping[str, Any], allowed_set: Any) -> list[str]:
    """Core's ``final_scan`` over a whole cassette's scan view (the write path's last pass)."""
    core = require_core()
    found: list[str] = core.final_scan(expand(cassette_doc), allowed_set)
    return found


def fixture_set() -> Any:
    """The allowed set of a take: fixture data ONLY (the ``evalfx-`` prefix, the fixture list and
    its public repositories). Nothing an answer carries is ever added (OVN-miassist-eval-20)."""
    from pathlib import Path

    core = require_core()
    return core.AllowedSet.from_fixtures(Path(__file__).resolve().parents[1] / "fixtures.yaml")


def object_array(
    schema: Any, components: Mapping[str, Any], depth: int = 0, seen: tuple[str, ...] = ()
) -> tuple[str, Mapping[str, Any]] | None:
    """Where a 2xx schema holds an array of objects (``""`` at the top, ``"field"`` one or two
    fields deep) and the schema of one item (its ``$ref`` resolved), or None."""
    if depth > 6 or not isinstance(schema, Mapping):
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[1]
        if name in seen:
            return None
        return object_array(components.get(name, {}), components, depth, (*seen, name))
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            found = object_array(sub, components, depth, seen)
            if found is not None:
                return found
    if schema.get("type") == "array":
        item = schema.get("items", {})
        if isinstance(item, Mapping) and isinstance(item.get("$ref"), str):
            item = components.get(str(item["$ref"]).rsplit("/", 1)[1], {})
        if isinstance(item, Mapping) and (
            item.get("type") == "object" or "properties" in item or item.get("additionalProperties")
        ):
            return "", item
        return None
    if depth < 2:
        for prop, sub in (schema.get("properties") or {}).items():
            found = object_array(sub, components, depth + 1, seen)
            if found is not None:
                return f"{prop}.{found[0]}".strip("."), found[1]
    return None


def schema_object_array(
    schema: Any, components: Mapping[str, Any], depth: int = 0, seen: tuple[str, ...] = ()
) -> str | None:
    """Where a 2xx schema holds an array of objects, or None. Static half of FR-002.14c (FTID §3.16
    ``uncovered_list_routes``)."""
    found = object_array(schema, components, depth, seen)
    return None if found is None else found[0]


def item_fields(item: Mapping[str, Any]) -> frozenset[str]:
    """The field names one list item's schema declares (empty when it declares none)."""
    return frozenset(str(k) for k in (item.get("properties") or {}))


def list_id(item: Mapping[str, Any], template: str, refdoc: Any) -> str | None:
    """The field that identifies one item of the list at ``template``, read from the item's schema
    (FU-10): ``id`` when the item has it, else the parameter of the list's own item read
    (``GET <template>/{param}``) when the item has a field of that name, else None: a profile then
    claims no id rather than one the answer does not carry (``candidates`` are keyed
    ``candidate_id``; a held-out use has no single id)."""
    fields = item_fields(item)
    if "id" in fields:
        return "id"
    prefix = template.rstrip("/") + "/{"
    for route in refdoc.routes:
        template_of: str = str(route.template)
        rest = template_of[len(prefix) :]
        if route.method == "GET" and template_of.startswith(prefix) and rest.endswith("}"):
            param = rest[:-1]
            if "/" not in param and "}" not in param and param in fields:
                return param
    return None


def uncovered_list_routes(refdoc: Any, profile: Mapping[str, Any]) -> list[str]:
    """Reference GETs whose 2xx schema holds an array of objects and that have neither a ``list``
    entry nor ``list: none`` with a reason (FR-002.14c, static)."""
    covered = {
        (r["method"], r["route"])
        for r in profile.get("routes", [])
        if "list" in r and (r["list"] != "none" or r.get("reason"))
    }
    components = refdoc.openapi.get("components", {}).get("schemas", {})
    out = []
    for route in refdoc.routes:
        if route.method != "GET" or (route.method, route.template) in covered:
            continue
        for status, entry in route.op.get("responses", {}).items():
            if not status.startswith("2"):
                continue
            schema = ((entry.get("content") or {}).get("application/json") or {}).get("schema")
            if schema_object_array(schema, components) is not None:
                out.append(route.key)
                break
    return out
