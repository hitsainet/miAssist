"""The full reference OpenAPI per app (FR-002.7, FR-002.9, FR-002.12; FTID §3.1, TD-3).

``eval/reference/openapi/<app>.json`` holds ``{app, fetched_on, app_version, source, openapi}``.
Routes are compiled from ``paths``; a literal segment wins over a parameter, then the longer
template. Answers validate with ``jsonschema`` (Draft 2020-12) through a ``referencing`` registry
over ``#/components/schemas``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from miassist_eval import classes
from miassist_eval.canonical import sha256

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
APPS = ("miworkbench", "miserver", "midataworks", "miforge")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PARAM = re.compile(r"\{([^}/]+)\}")
_DOC_URI = "urn:miassist-eval:openapi"


def ref_dir() -> Path:
    return Path(
        os.environ.get("MIASSIST_EVAL_REF_OPENAPI_DIR", EVAL_ROOT / "reference" / "openapi")
    )


def snapshot_dir() -> Path:
    return Path(os.environ.get("MIASSIST_ROUTE_SNAPSHOT_DIR", REPO_ROOT / "tests/fixtures/openapi"))


@dataclass(frozen=True)
class Route:
    app: str
    method: str
    template: str
    regex: re.Pattern[str]
    literal_segments: int
    op: dict[str, Any] = field(hash=False, compare=False)

    def params(self, path: str) -> dict[str, str]:
        match = self.regex.fullmatch(path)
        return match.groupdict() if match else {}

    @property
    def key(self) -> str:
        return f"{self.method} {self.template}"


@dataclass
class RefDoc:
    app: str
    openapi: dict[str, Any]
    fetched_on: date
    app_version: str
    source: str
    routes: list[Route]
    sha256: str
    _registry: Registry[Any] | None = None

    def route(self, method: str, template: str) -> Route | None:
        for r in self.routes:
            if r.method == method and r.template == template:
                return r
        return None

    @property
    def registry(self) -> Registry[Any]:
        if self._registry is None:
            resource = Resource.from_contents(self.openapi, default_specification=DRAFT202012)
            self._registry = Registry().with_resource(_DOC_URI, resource)
        return self._registry


def compile_template(template: str) -> tuple[re.Pattern[str], int]:
    parts = _PARAM.split(template)
    pattern = "".join(
        re.escape(p) if i % 2 == 0 else f"(?P<{_safe(p)}>[^/]+)" for i, p in enumerate(parts)
    )
    literal = sum(1 for seg in template.strip("/").split("/") if seg and not _PARAM.fullmatch(seg))
    return re.compile(pattern), literal


def _safe(name: str) -> str:
    return re.sub(r"\W", "_", name)


def build(app: str, wrapper: dict[str, Any]) -> RefDoc:
    openapi = wrapper["openapi"]
    routes: list[Route] = []
    for template, item in sorted(openapi.get("paths", {}).items()):
        regex, literal = compile_template(template)
        for method in METHODS:
            op = item.get(method.lower())
            if isinstance(op, dict):
                routes.append(Route(app, method, template, regex, literal, op))
    fetched = wrapper.get("fetched_on", "1970-01-01")
    return RefDoc(
        app=app,
        openapi=openapi,
        fetched_on=date.fromisoformat(str(fetched)[:10]),
        app_version=str(wrapper.get("app_version", "")),
        source=str(wrapper.get("source", "")),
        routes=routes,
        sha256=sha256(openapi),
    )


def load(app: str, directory: Path | None = None) -> RefDoc:
    path = (directory or ref_dir()) / f"{app}.json"
    if not path.is_file():
        raise classes.Refusal(classes.REFERENCE_MISSING, str(path))
    return build(app, json.loads(path.read_text(encoding="utf-8")))


def resolve(doc: RefDoc, method: str, path: str) -> Route | None:
    """The reference route for ``(method, path)``: most literal segments, then longest template."""
    candidates = [r for r in doc.routes if r.method == method and r.regex.fullmatch(path)]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.literal_segments, len(r.template)), reverse=True)
    return candidates[0]


def _validate(doc: RefDoc, schema: dict[str, Any], instance: Any, where: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(_rebase(schema), registry=doc.registry)
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        path = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path)
        out.append(f"{where}{path}: {err.message[:200]}")
    return out


def _rebase(node: Any) -> Any:
    """Point ``#/components/...`` references at the registered document."""
    if isinstance(node, dict):
        out = {k: _rebase(v) for k, v in node.items()}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            out["$ref"] = f"{_DOC_URI}{ref}"
        return out
    if isinstance(node, list):
        return [_rebase(v) for v in node]
    return node


def response_schema(route: Route, status: int) -> dict[str, Any] | None:
    responses = route.op.get("responses", {})
    entry = responses.get(str(status))
    if entry is None:
        return None
    content = entry.get("content") or {}
    schema = (content.get("application/json") or {}).get("schema")
    return schema if isinstance(schema, dict) else {}


def validate_answer(doc: RefDoc, route: Route, status: int, body: Any) -> list[str]:
    """JSON paths of ``body`` that fail the route's documented answer for ``status``."""
    if str(status) not in route.op.get("responses", {}):
        if status >= 400:
            return []  # an app's own error answer; undocumented errors are not drift
        return [f"answer: {status} not documented"]
    schema = response_schema(route, status)
    if not schema or status >= 400:
        return []
    return _validate(doc, schema, body, "answer")


def validate_request(
    doc: RefDoc, route: Route, path: str, query: dict[str, Any], body: Any
) -> list[str]:
    """JSON paths of the request that fail the operation's parameters and requestBody (R1M-17)."""
    out: list[str] = []
    params = route.params(path)
    for p in route.op.get("parameters", []):
        name, where = p.get("name"), p.get("in")
        source: dict[str, Any] = params if where == "path" else query if where == "query" else {}
        if where not in ("path", "query"):
            continue
        if name not in source:
            if p.get("required"):
                out.append(f"request.{where}.{name}: required")
            continue
        schema = p.get("schema") or {}
        value = _coerce(source[name], schema)
        out += _validate(doc, schema, value, f"request.{where}.{name}")
    rb = route.op.get("requestBody")
    if isinstance(rb, dict):
        schema = ((rb.get("content") or {}).get("application/json") or {}).get("schema")
        if body is None:
            if rb.get("required"):
                out.append("request.body: required")
        elif isinstance(schema, dict):
            out += _validate(doc, schema, body, "request.body")
    return out


def _coerce(value: Any, schema: dict[str, Any]) -> Any:
    """Query and path values arrive as strings; read them as the schema's scalar type."""
    if not isinstance(value, str):
        return value
    kinds = {schema.get("type")} | {
        s.get("type") for s in schema.get("anyOf", []) if isinstance(s, dict)
    }
    if "integer" in kinds and re.fullmatch(r"-?\d+", value):
        return int(value)
    if "number" in kinds and re.fullmatch(r"-?\d+(\.\d+)?", value):
        return float(value)
    if "boolean" in kinds and value.lower() in {
        "1",
        "true",
        "yes",
        "on",
        "t",
        "y",
        "0",
        "false",
        "no",
        "off",
        "f",
        "n",
    }:
        return value.lower() in {"1", "true", "yes", "on", "t", "y"}
    return value


def _op_schemas(op: dict[str, Any]) -> dict[str, Any]:
    rb = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {})
    ok = {
        s: ((e.get("content") or {}).get("application/json") or {}).get("schema")
        for s, e in (op.get("responses") or {}).items()
        if s.startswith("2")
    }
    return {"request": rb.get("schema"), "responses": ok}


def agrees_with_snapshot(ref: RefDoc, snapshot: dict[str, Any]) -> list[str]:
    """Every route in 001's snapshot must exist in the reference with the same request and 2xx
    schemas (both resolved); [] when they agree (FR-002.12: two sources, not one)."""
    components = ref.openapi.get("components", {}).get("schemas", {})
    out = []
    for template, item in sorted(snapshot.get("paths", {}).items()):
        for method, snap_op in item.items():
            route = ref.route(method.upper(), template)
            if route is None:
                out.append(f"{method.upper()} {template}: absent from the reference")
                continue
            mine = _resolve(_op_schemas(route.op), components)
            theirs = _op_schemas(snap_op)
            if sha256(_strip_titles(mine["request"])) != sha256(_strip_titles(theirs["request"])):
                out.append(f"{method.upper()} {template}: request schema differs")
            for status, schema in theirs["responses"].items():
                if sha256(_strip_titles(mine["responses"].get(status))) != sha256(
                    _strip_titles(schema)
                ):
                    out.append(f"{method.upper()} {template}: {status} schema differs")
    return out


def _resolve(node: Any, components: dict[str, Any], depth: int = 0) -> Any:
    """Inline ``#/components/schemas/X`` the way 001's snapshot script does (cycle-safe)."""
    if depth > 40:
        return {"x-truncated": True}
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            target = components.get(ref.rsplit("/", 1)[1], {})
            merged = {k: v for k, v in node.items() if k != "$ref"}
            return {**_resolve(target, components, depth + 1), **merged}
        return {k: _resolve(v, components, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, components, depth + 1) for v in node]
    return node


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k not in ("title", "description")}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


PROSE_KEYS = frozenset({"description", "summary"})


def strip_prose(node: Any) -> Any:
    """The reference keeps routes and schemas, never the apps' prose (descriptions and summaries):
    validation ignores it, and an app's sentence can read like a credential to the repository's
    secret scan (OVN-miassist-eval-18)."""
    if isinstance(node, dict):
        return {
            k: strip_prose(v)
            for k, v in node.items()
            if not (k in PROSE_KEYS and isinstance(v, str))
        }
    if isinstance(node, list):
        return [strip_prose(v) for v in node]
    return node


def age_days(doc: RefDoc, now: datetime | None = None) -> int:
    today = (now or datetime.now(UTC)).date()
    return (today - doc.fetched_on).days


def refresh(app: str, live_url: str) -> RefDoc:  # pragma: no cover - workstation only (FTASKS 1.5)
    """Workstation only: ``GET`` the live app's OpenAPI route and write it with the date."""
    import httpx

    doc = httpx.get(live_url, timeout=30).json()
    wrapper = {
        "app": app,
        "fetched_on": datetime.now(UTC).date().isoformat(),
        "app_version": str(doc.get("info", {}).get("version", "")),
        "source": f"live:{live_url}",
        "openapi": strip_prose(doc),
    }
    path = ref_dir() / f"{app}.json"
    path.write_text(json.dumps(wrapper, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return build(app, wrapper)
