"""The committed route profiles are what ``eval/scripts/write_route_profiles.py`` writes from the
committed reference (final re-vendor, 2026-11-17).

``test_list_routes_covered.py`` flags only a GET whose 2xx schema holds an array of objects, so a
reference refresh without a profile refresh stayed green: at the 2026-11-17 re-vendor the old
profiles (no entries for the new WSP GETs, miForge's typed approval list still read as ``items: '*'``)
passed every eval test. The profiles are generated, so the check is that they regenerate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from miassist_eval import openapi_ref

EVAL_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = EVAL_ROOT / "scripts" / "write_route_profiles.py"


def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("write_route_profiles", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_the_committed_profile_regenerates(app: str) -> None:
    committed = yaml.safe_load((EVAL_ROOT / "route_profiles" / f"{app}.yaml").read_text())
    assert committed == generator().profile(app), (
        f"eval/route_profiles/{app}.yaml is not what the generator writes from the reference; "
        "refresh: eval/.venv/bin/python eval/scripts/write_route_profiles.py"
    )
