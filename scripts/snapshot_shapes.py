"""Snapshot the RESPONSE shapes of every app route miAssist calls (R1 review fix OR1-pb-1..5, OVN-17).

    python -m scripts.snapshot_shapes --app midataworks --ref 58087b1 [--repo DIR]

The playbooks' tests answer from hand-written fakes. A fake whose answer the real app never gives
lets a playbook agree with its fake by construction (review round 1: seven high findings). This
script vendors, per app, the shape of every answer a registered route (plus the source file's
``extra_routes``) can give, so ``tests/support/shapes.py`` can refuse a fake answer that is not one.

Each status's schema comes from one of three places, recorded per entry (``from``):

- ``openapi``: the app's own OpenAPI response schema, produced in the app's interpreter from a
  ``git archive`` of ``ref`` (``scripts.snapshot_openapi.export``; nothing is written in the app);
- ``model``: ``<Model>.model_json_schema()`` of named classes, imported in the same interpreter,
  placed at a JSON pointer (for a route that declares ``dict`` while its code fills a model);
- ``code``: a schema hand-derived from cited code, only where neither exists.

Inputs: ``tests/fixtures/openapi/response_sources/<app>.json`` (``extra_routes`` and ``overlays``;
every ``model`` and ``code`` overlay carries its ``cite``). Output: the ONE shapes file the suite uses
(003's format, ``tests/support/response_shapes.py``): ``tests/fixtures/openapi/responses.json``,
``apps.<app> = {commit, routes: {"METHOD /path": {"<status>": {schema, source}}}}``. Only the entries
the OpenAPI snapshot cannot give are written (an overlaid route, or a route the snapshot does not
pin); each carries ``"generated": "scripts/snapshot_shapes.py"`` and is replaced on a re-run, while
hand-derived entries (003's) are kept. Model-derived parts are written as sent (every field
present, objects closed: ``response_shapes.all_required``); code-derived parts as written.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.snapshot_openapi import HOME_APPS, IMPORT_ENV, RECIPES, export, interpreter


def all_required(schema: Any) -> Any:
    """As sent: every property present, objects closed (``tests/support/response_shapes``)."""
    if isinstance(schema, dict):
        out = {k: all_required(v) for k, v in schema.items()}
        if isinstance(out.get("properties"), dict):
            out["required"] = sorted(out["properties"])
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(schema, list):
        return [all_required(v) for v in schema]
    return schema


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI = REPO_ROOT / "tests" / "fixtures" / "openapi"
SOURCES = OPENAPI / "response_sources"
RESPONSES = OPENAPI / "responses.json"
GENERATED = "scripts/snapshot_shapes.py"

EMIT = r"""
import importlib, json, os, sys
sys.path.insert(0, ".")
try:
    from cryptography.fernet import Fernet
    os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
except Exception:
    pass
{code}
models = {{}}
for dotted in {classes!r}:
    module, _, name = dotted.partition(":")
    models[dotted] = getattr(importlib.import_module(module), name).model_json_schema()
sys.stdout.write("\n@@SHAPES@@" + json.dumps({{"openapi": app.openapi(), "models": models}}))
"""


def resolve(node: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """Inline every ``#/components/schemas/X`` and ``#/$defs/X`` reference (cycle-safe)."""
    if depth > 60:
        return {"x-truncated": True}
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and (
            ref.startswith("#/components/schemas/") or ref.startswith("#/$defs/")
        ):
            target = defs.get(ref.rsplit("/", 1)[1], {})
            rest = {k: v for k, v in node.items() if k != "$ref"}
            return {**resolve(target, defs, depth + 1), **resolve(rest, defs, depth + 1)}
        return {k: resolve(v, defs, depth + 1) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [resolve(v, defs, depth + 1) for v in node]
    return node


def _model_schema(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = resolve(raw, raw.get("$defs", {}))
    return out


def _put(schema: dict[str, Any], pointer: str, value: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with the node at JSON ``pointer`` replaced by ``value`` (``""``: the whole)."""
    if pointer in ("", "/"):
        return value
    out = copy.deepcopy(schema)
    node: Any = out
    parts = pointer.strip("/").split("/")
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


def emit(app: str, tree: Path, classes: list[str], python: Path | None = None) -> dict[str, Any]:
    recipe = RECIPES[app]
    scratch = tree / ".snapshot-data"
    scratch.mkdir(exist_ok=True)
    env = {
        **os.environ,
        **IMPORT_ENV,
        "DATA_DIR": str(scratch),
        "HF_HOME": str(scratch / "hf"),
        "HF_CACHE_DIR": str(scratch / "hf"),
    }
    result = subprocess.run(
        [
            str(python or interpreter(app)),
            "-B",
            "-c",
            EMIT.format(code=recipe["code"], classes=classes),
        ],
        cwd=tree / recipe["cwd"],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if "@@SHAPES@@" not in result.stdout:
        raise SystemExit(f"{app}: no shapes ({result.stderr[-2000:]})")
    loaded: dict[str, Any] = json.loads(result.stdout.split("@@SHAPES@@", 1)[1])
    return loaded


def route_keys(app: str, extra: list[str]) -> list[str]:
    from miassist.adapters.routes import ROUTES

    keys = {f"{r.method} {r.path}" for r in ROUTES.for_app(app)}
    return sorted(keys | set(extra))


def build(app: str, openapi: dict[str, Any], models: dict[str, Any], src: dict[str, Any]) -> Any:
    components = openapi.get("components", {}).get("schemas", {})
    routes: dict[str, Any] = {}
    for key in route_keys(app, list(src.get("extra_routes", []))):
        method, path = key.split(" ", 1)
        op = openapi.get("paths", {}).get(path, {}).get(method.lower())
        if op is None:
            raise SystemExit(f"{app}: {key} is not in the app's OpenAPI")
        statuses: dict[str, Any] = {}
        for status, answer in sorted(op.get("responses", {}).items()):
            if not status.startswith("2"):
                continue
            raw = (answer.get("content") or {}).get("application/json", {}).get("schema", {})
            statuses[status] = {"from": "openapi", "schema": all_required(resolve(raw, components))}
        routes[key] = statuses
    for overlay in src.get("overlays", []):
        key, status = overlay["route"], str(overlay["status"])
        if overlay["from"] == "model":
            variants = [all_required(_model_schema(models[c])) for c in overlay["classes"]]
            value: dict[str, Any] = variants[0] if len(variants) == 1 else {"anyOf": variants}
        else:
            value = overlay["schema"]
        if overlay.get("wrap") == "array":
            value = {"type": "array", "items": value}
        if overlay.get("nullable"):
            value = {"anyOf": [value, {"type": "null"}]}
        if overlay.get("pointer", "") not in ("", "/") and status not in routes.get(key, {}):
            raise SystemExit(f"{key} {status}: an overlay at a pointer needs the app's own entry")
        entry = routes.setdefault(key, {}).get(status, {"from": overlay["from"], "schema": {}})
        whole = overlay.get("pointer", "") in ("", "/")
        if whole and overlay.get("mode") == "anyOf":  # another answer the same status can carry
            value = {"anyOf": [entry["schema"], value]}
        entry = {
            "from": overlay["from"] if whole and overlay.get("mode") != "anyOf" else entry["from"],
            "schema": _put(entry["schema"], overlay.get("pointer", ""), value),
            **({"cite": entry["cite"]} if "cite" in entry else {}),
        }
        cites = [c for c in (entry.get("cite"), overlay["cite"]) if c]
        entry["cite"] = "; ".join(dict.fromkeys(cites))
        routes[key][status] = entry
    return routes


def entries(
    app: str, routes: dict[str, Any], pinned: dict[str, Any], extra: list[str]
) -> dict[str, Any]:
    """The routes the OpenAPI snapshot cannot give: overlaid, not pinned there, or listed as
    ``extra_routes`` (so the file is the same on every branch, whatever it registers)."""
    out: dict[str, Any] = {}
    for key, statuses in routes.items():
        method, path = key.split(" ", 1)
        unpinned = key in extra or method.lower() not in pinned.get(path, {})
        for status, entry in statuses.items():
            if entry["from"] == "openapi" and "cite" not in entry and not unpinned:
                continue
            source = entry.get("cite") or f"the app's OpenAPI response model at the commit ({app})"
            out.setdefault(key, {})[status] = {
                "schema": entry["schema"],
                "source": source,
                "generated": GENERATED,
            }
    return out


def write(app: str, sha: str, generated: dict[str, Any]) -> None:
    data: dict[str, Any] = (
        json.loads(RESPONSES.read_text()) if RESPONSES.is_file() else {"about": "", "apps": {}}
    )
    data.setdefault("about", "Response shapes of the app routes the playbooks' fakes answer.")
    block = data["apps"].setdefault(app, {"commit": sha, "routes": {}})
    if block.get("commit") != sha:
        raise SystemExit(f"{app}: responses.json is at {block.get('commit')}, not {sha}")
    kept = {
        route: {s: e for s, e in statuses.items() if e.get("generated") != GENERATED}
        for route, statuses in block["routes"].items()
    }
    merged = {route: statuses for route, statuses in kept.items() if statuses}
    for route, statuses in generated.items():
        slot = merged.setdefault(route, {})
        for status, entry in statuses.items():
            # a hand-derived entry (003's) for the same route and status is kept, as the module
            # says (integration OVN-miassist-int-17: ``update`` replaced it)
            slot.setdefault(status, entry)
    block["routes"] = dict(sorted(merged.items()))
    RESPONSES.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=sorted(RECIPES))
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--repo", type=Path, default=None, help="the app's repository")
    args = parser.parse_args(argv)
    src = json.loads((SOURCES / f"{args.app}.json").read_text())
    classes = sorted({c for o in src.get("overlays", []) for c in o.get("classes", [])})
    repo = args.repo or HOME_APPS / RECIPES[args.app]["folder"]
    tree, sha = export(RECIPES[args.app]["folder"], args.ref, repo)
    loaded = emit(args.app, tree, classes)
    routes = build(args.app, loaded["openapi"], loaded["models"], src)
    pinned = json.loads((OPENAPI / f"{args.app}.json").read_text())
    generated = entries(args.app, routes, pinned["paths"], list(src.get("extra_routes", [])))
    write(args.app, pinned["commit"] if pinned["commit"].startswith(sha[:7]) else sha, generated)
    print(f"{args.app}@{sha}: {len(generated)} routes written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
