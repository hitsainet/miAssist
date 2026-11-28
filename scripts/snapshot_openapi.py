"""Snapshot each app's OpenAPI for the route pins (001 FTASKS 4.4; FTID §2, R3M-6, L-9).

    python -m scripts.snapshot_openapi [--app miserver ...] [--source DIR]

For each app, the app's OpenAPI document is produced IN THE APP'S OWN INTERPRETER (its venv), from a
source tree: by default a ``git archive`` of the sibling's committed HEAD exported to a temporary
directory (so uncommitted work in a sibling tree never reaches a snapshot, and nothing is written in
it). ``--source app=DIR`` names another committed tree (e.g. a builder's branch export). Two files
are written per app under ``tests/fixtures/openapi/``:

- ``<app>.json``: the path items of the routes miAssist registers, with request schemas resolved
  (``$ref``s inlined), which Core's pre-filing check reads; for miWorkbench also ``CALLER_TOOLS``
  and ``gated_routes``, every ``[method, path, action]`` its live registry gates (045-A0's
  ``src.core.approval_gate.gated_routes(app)``; it publishes no ``x-approval-action`` markers,
  OVN-miassist-w-1); plus provenance (commit, date).
- ``<app>.index.json``: the app's FULL route index, every ``(method, path, request content types)``
  with gate markers and no schemas (A14's never-routes are matched against it).
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "tests" / "fixtures" / "openapi"
HOME_APPS = Path(os.environ.get("MIASSIST_SIBLINGS_ROOT", Path.home() / "app" / "miStudio"))

#: How each app's OpenAPI is produced: its folder, interpreter, import directory and statement.
RECIPES: dict[str, dict[str, str]] = {
    "miworkbench": {
        "folder": "miWorkbench",
        "python": "backend/venv/bin/python",
        "cwd": "backend",
        "code": "from src.main import app",
        "caller_tools": "from src.api.v1.endpoints.mcp_approvals import CALLER_TOOLS",
        # 045-A0 publishes no x-approval-action markers: its gate lives in code, so the gated list
        # is derived from the live registry, as CALLER_TOOLS is (OVN-miassist-w-1).
        "gated_routes": "from src.core.approval_gate import gated_routes",
    },
    "miserver": {
        "folder": "miServer",
        "python": "venv/bin/python",
        "cwd": ".",
        "code": "from miserver.main import create_app; app = create_app()",
    },
    "midataworks": {
        "folder": "miDataworks",
        "python": "backend/.venv/bin/python",
        "cwd": "backend",
        "code": "from src.main import fastapi_app as app",
    },
    "miforge": {
        "folder": "miForge",
        "python": ".venv/bin/python",
        "cwd": "backend/src",
        "code": "from api.app import create_app; app = create_app()",
    },
}

#: Placeholder environment some apps need to IMPORT (never to connect); nothing here is a secret.
IMPORT_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://snapshot:placeholder@127.0.0.1:1/snapshot",
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "INTERNAL_API_SECRET": "snapshot-import-only",
    "CELERY_BROKER_URL": "redis://127.0.0.1:1/0",
    "CELERY_RESULT_BACKEND": "redis://127.0.0.1:1/0",
    "SECRET_KEY": "snapshot-import-only-placeholder-value-32",
}

EMIT = r"""
import json, os, sys
sys.path.insert(0, ".")
try:
    from cryptography.fernet import Fernet
    os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
except Exception:
    pass
{code}
out = {{"openapi": app.openapi()}}
{caller}
{gated}
sys.stdout.write("\n@@SNAPSHOT@@" + json.dumps(out))
"""


def export(folder: str, ref: str, repo: Path | None = None) -> tuple[Path, str]:
    """``git archive`` of ``ref`` in the sibling (``repo``, default the folder under
    ``HOME_APPS``), extracted to a temporary directory that is removed when the process exits (every
    caller uses it within the run; before 2026-11-19 none removed it, and some 1,370 exports, about
    56 GB, had piled up under /tmp). Nothing is written in the sibling."""
    repo = repo if repo is not None else HOME_APPS / folder
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", ref],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    target = Path(tempfile.mkdtemp(prefix=f"snapshot-{folder}-"))
    atexit.register(shutil.rmtree, target, ignore_errors=True)
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", ref], capture_output=True, check=True
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
    return target, sha


def interpreter(app: str, root: Path | None = None) -> Path:
    """The sibling's own interpreter: in ``root`` if it has one, else in its main tree."""
    recipe = RECIPES[app]
    if root is not None and (root / recipe["python"]).is_file():
        return root / recipe["python"]
    return HOME_APPS / recipe["folder"] / recipe["python"]


def emit(app: str, tree: Path, python: Path | None = None) -> dict[str, Any]:
    recipe = RECIPES[app]
    python = python if python is not None else interpreter(app)
    caller = (
        f"{recipe['caller_tools']}\nout['caller_tools'] = sorted(CALLER_TOOLS)"
        if "caller_tools" in recipe
        else ""
    )
    gated = (
        "try:\n"
        f"    {recipe['gated_routes']}\n"
        "except ImportError:\n"
        "    out['gated_routes'] = None\n"
        "else:\n"
        "    out['gated_routes'] = sorted([m, p, a] for (m, p), a in gated_routes(app).items())"
        if "gated_routes" in recipe
        else ""
    )
    code = EMIT.format(code=recipe["code"], caller=caller, gated=gated)
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
        [str(python), "-B", "-c", code],
        cwd=tree / recipe["cwd"],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if "@@SNAPSHOT@@" not in result.stdout:
        raise SystemExit(f"{app}: no snapshot ({result.stderr[-2000:]})")
    loaded: dict[str, Any] = json.loads(result.stdout.split("@@SNAPSHOT@@", 1)[1])
    return loaded


def resolve(node: Any, components: dict[str, Any], depth: int = 0) -> Any:
    """Inline every ``#/components/schemas/X`` reference (cycle-safe by depth)."""
    if depth > 40:
        return {"x-truncated": True}
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            target = components.get(ref.rsplit("/", 1)[1], {})
            merged = {k: v for k, v in node.items() if k != "$ref"}
            return {**resolve(target, components, depth + 1), **merged}
        return {k: resolve(v, components, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v, components, depth + 1) for v in node]
    return node


METHODS = ("get", "post", "put", "patch", "delete")

#: The gate markers the route index keeps per route. ``x-approval-escalation`` (miForge's
#: ``mark_gated_routes``) names the OTHER action a marked route's call can wait as instead, chosen
#: per request (``gpu_start`` -> ``hotupdate_attach``, ``wsp_session`` -> ``wsp_session_external``),
#: so ``classify_marker`` refuses a route that carries it (FU-10; OVN-miassist-1124-4).
GATE_MARKERS = ("x-approval-action", "x-approval-when", "x-approval-escalation")


def route_index(openapi: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for path, item in sorted(openapi.get("paths", {}).items()):
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            content = sorted((op.get("requestBody") or {}).get("content", {}))
            row: dict[str, Any] = {"method": method.upper(), "path": path, "content_types": content}
            for marker in GATE_MARKERS:
                if marker in op:
                    row[marker] = op[marker]
            rows.append(row)
    return rows


def registered_items(app: str, openapi: dict[str, Any]) -> dict[str, Any]:
    from miassist.adapters.routes import ROUTES

    components = openapi.get("components", {}).get("schemas", {})
    items: dict[str, Any] = {}
    for route in ROUTES.for_app(app):
        op = openapi.get("paths", {}).get(route.path, {}).get(route.method.lower())
        if op is None:
            continue
        kept = {k: op[k] for k in ("parameters", "requestBody", "responses") if k in op}
        kept.update({k: v for k, v in op.items() if k.startswith("x-")})
        items.setdefault(route.path, {})[route.method.lower()] = resolve(kept, components)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", action="append", choices=sorted(RECIPES))
    parser.add_argument("--ref", action="append", default=[], help="app=REF (default HEAD)")
    args = parser.parse_args(argv)
    refs = dict(item.split("=", 1) for item in args.ref)
    OUT.mkdir(parents=True, exist_ok=True)
    for app in args.app or sorted(RECIPES):
        tree, sha = export(RECIPES[app]["folder"], refs.get(app, "HEAD"))
        snap = emit(app, tree)
        openapi = snap["openapi"]
        provenance = {
            "app": app,
            "commit": sha,
            "ref": refs.get(app, "HEAD"),
            "taken": datetime.now(UTC).date().isoformat(),
        }
        index = {**provenance, "routes": route_index(openapi)}
        (OUT / f"{app}.index.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
        pins: dict[str, Any] = {**provenance, "paths": registered_items(app, openapi)}
        if "caller_tools" in snap:
            pins["caller_tools"] = snap["caller_tools"]
        if snap.get("gated_routes") is not None:
            pins["gated_routes"] = snap["gated_routes"]
        (OUT / f"{app}.json").write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")
        print(f"{app}@{sha}: {len(index['routes'])} routes, {len(pins['paths'])} pinned paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
