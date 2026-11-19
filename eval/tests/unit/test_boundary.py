"""FR-002.1 and FR-002.2: the harness loads no miAssist server module and no app package."""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
import subprocess
import sys
from pathlib import Path

import miassist_eval

EVAL_ROOT = Path(__file__).resolve().parents[2]
SERVER_PACKAGE = "miassist"
APP_PACKAGES = ("src", "miserver", "millm", "api", "mcp_server")
APP_DISTRIBUTIONS = (
    "miassist",
    "miworkbench",
    "miserver",
    "millm",
    "midataworks",
    "miforge",
    "mistudio",
)


def all_modules() -> list[str]:
    names = ["miassist_eval"]  # __main__ runs the CLI on import: excluded
    for info in pkgutil.walk_packages(miassist_eval.__path__, "miassist_eval."):
        if info.name != "miassist_eval.__main__":
            names.append(info.name)
    return names


def test_every_module_is_walked() -> None:
    names = all_modules()
    assert "miassist_eval.recorder" in names and "miassist_eval.drivers.claude_code" in names


def test_no_server_module_is_loaded_after_importing_every_module() -> None:
    """In a fresh interpreter, import every harness module, then read the LIVE sys.modules."""
    code = (
        "import importlib, sys\n"
        f"for n in {all_modules()!r}: importlib.import_module(n)\n"
        "bad = sorted(m for m in sys.modules if m == 'miassist' or m.startswith('miassist.'))\n"
        f"apps = sorted(m for m in sys.modules if m.split('.')[0] in {APP_PACKAGES!r})\n"
        "print(repr((bad, apps)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=EVAL_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": f"{EVAL_ROOT}:{EVAL_ROOT.parent}", "PATH": "/usr/bin"},
    )
    bad, apps = eval(out.stdout.strip().splitlines()[-1])  # noqa: S307 - our own repr
    assert bad == [], f"the harness loaded the miAssist server package: {bad}"
    assert apps == [], f"the harness loaded an app package: {apps}"


def test_the_fixture_filter_is_not_the_server_package() -> None:
    from miassist_eval import allowed

    assert allowed.CORE is not None
    assert allowed.CORE.__name__ == "miassist_fixtures.filter"


def test_no_app_distribution_is_installed() -> None:
    """FR-002.2: the evaluation environment holds no app (or server) distribution."""
    installed = {d.metadata["Name"].lower() for d in importlib.metadata.distributions()}
    found = sorted(installed & set(APP_DISTRIBUTIONS))
    assert found == [], f"app distributions installed in the evaluation environment: {found}"


def test_server_package_is_not_importable_by_name_from_eval_path() -> None:
    """The server lives under src/, which is never on the harness path."""
    spec = importlib.util.find_spec(SERVER_PACKAGE)
    assert spec is None, f"{SERVER_PACKAGE} is importable from the evaluation path: {spec.origin}"
