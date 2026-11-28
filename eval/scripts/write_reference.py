"""Write a PROVISIONAL reference OpenAPI per app from the app's committed code (OVN-miassist-eval-2).

    eval/.venv/bin/python eval/scripts/write_reference.py app=REF ...

FTASKS 1.5 fetches the reference from each LIVE app on the workstation. Until that reading exists,
this script produces the same document from a ``git archive`` of a committed ref, in the app's own
interpreter, through Core's ``scripts/snapshot_openapi.py`` (``export``/``emit``); nothing is written
in the sibling. ``source`` says ``code:<app>@<commit>`` so no reader mistakes it for a live fetch.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.snapshot_openapi import RECIPES, emit, export  # noqa: E402

sys.path.insert(0, str(REPO / "eval"))
from miassist_eval.openapi_ref import strip_prose  # noqa: E402

OUT = REPO / "eval" / "reference" / "openapi"


def main(argv: list[str]) -> int:
    refs = dict(a.split("=", 1) for a in argv) or {a: "HEAD" for a in RECIPES}
    for app, ref in refs.items():
        tree, sha = export(RECIPES[app]["folder"], ref)
        try:
            openapi = emit(app, tree)["openapi"]
        finally:
            shutil.rmtree(tree, ignore_errors=True)
        wrapper = {
            "app": app,
            "fetched_on": datetime.now(UTC).date().isoformat(),
            "app_version": str(openapi.get("info", {}).get("version", "")),
            "source": f"code:{app}@{sha}",
            "openapi": strip_prose(openapi),
        }
        (OUT / f"{app}.json").write_text(json.dumps(wrapper, indent=1, sort_keys=True) + "\n")
        print(f"{app}@{sha}: {len(openapi.get('paths', {}))} paths")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
