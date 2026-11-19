"""Write the vendored request schemas of miWorkbench's file-first routes (003; OVN-miassist-pb003-1).

    python -m scripts.write_request_schemas

Reads the committed snapshot ``tests/fixtures/openapi/miworkbench.json`` (request schemas already
resolved by ``scripts/snapshot_openapi.py``) and writes, for every registered ``file_first`` route,
its declared query names and body schema to ``src/miassist/vendored/miworkbench_request_schemas.json``,
which Core's pre-filing check reads in production (``WorkbenchAdapter``'s schema lookup).
``tests/playbooks/detector_probe/test_request_schemas.py`` pins the file to a fresh derivation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "tests/fixtures/openapi/miworkbench.json"
TARGET = REPO_ROOT / "src/miassist/vendored/miworkbench_request_schemas.json"


def derive(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    from miassist.adapters.routes import ROUTES

    snap = snapshot if snapshot is not None else json.loads(SNAPSHOT.read_text())
    out: dict[str, Any] = {}
    for route in sorted(ROUTES.for_app("miworkbench"), key=lambda r: r.id):
        if not route.file_first:
            continue
        op = snap["paths"][route.path][route.method.lower()]
        params = [p for p in op.get("parameters", []) if p.get("in") == "query"]
        query = sorted(p["name"] for p in params)
        content = (op.get("requestBody") or {}).get("content", {})
        body = content.get("application/json", {}).get("schema")
        # R1 review fix (OR1-pb-7), 2026-11-16: the values too, so a request the app's own schema
        # refuses is refused here, before an approval is filed (and spent) for it.
        out[f"{route.method} {route.path}"] = {
            "query": query,
            "body": body,
            "query_schemas": {p["name"]: p.get("schema", {}) for p in params},
            "body_required": bool((op.get("requestBody") or {}).get("required")),
        }
    return {"commit": snap.get("commit"), "routes": out}


def text(snapshot: dict[str, Any] | None = None) -> str:
    return json.dumps(derive(snapshot), indent=1, sort_keys=True) + "\n"


def main() -> int:
    TARGET.write_text(text())
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
