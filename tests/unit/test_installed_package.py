"""The image carries every data file miAssist reads at run time (R3 review fix OR3-001-9, 2026-11-16).

The Dockerfile's build stage copies ``pyproject.toml README.md LICENSE src`` and runs
``pip install --no-compile .``, so only what ``[tool.setuptools.package-data]`` lists reaches the
image (miForge 017 shipped an image missing its data this way). This test does the same: it copies
exactly the Dockerfile's inputs, builds the wheel with the same build backend, installs (unpacks)
it into a throwaway directory, and then,
in a separate interpreter that sees ONLY the installed copy (``-I``, the copy first on the path,
``miassist.__file__`` asserted inside it), reads every data file and loads every runtime reader.

The wheel must carry every non-Python file under ``src/miassist`` (so a new data directory that is
not packaged fails here, not in production).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src/miassist"


def _data_files(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts
    }


def dockerfile_inputs() -> list[str]:
    """What the build stage copies before ``pip install`` (``COPY <a> <b> ... ./`` lines)."""
    text = (REPO_ROOT / "Dockerfile").read_text()
    build = text.split("FROM ", 2)[1]
    found: list[str] = []
    for line in build.splitlines():
        match = re.match(r"COPY\s+(?!--from)(.+)\s+\S+$", line.strip())
        if match:
            found += match.group(1).split()
    return found


def test_the_build_stage_copies_these_inputs() -> None:
    assert dockerfile_inputs() == ["pyproject.toml", "README.md", "LICENSE", "src"]


BUILD = "import sys; from setuptools import build_meta; build_meta.build_wheel(sys.argv[1])"


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("image")
    context = work / "context"
    context.mkdir()
    for name in dockerfile_inputs():
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(
                source, context / name, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
            )
        else:
            shutil.copy(source, context / name)
    # The same PEP 517 backend call ``pip install .`` makes (no pip, no network: setuptools is
    # pinned in the dev extra to the build-system pin).
    subprocess.run(
        [sys.executable, "-c", BUILD, str(work / "dist")],
        cwd=context,
        check=True,
        capture_output=True,
    )
    (wheel,) = (work / "dist").glob("miassist-*.whl")
    site = work / "site"
    with zipfile.ZipFile(wheel) as archive:  # a pure wheel installs by unpacking (--target)
        archive.extractall(site)
    return site


def test_the_wheel_carries_every_data_file(installed: Path) -> None:
    source = _data_files(PACKAGE)
    assert len(source) > 30
    shipped = _data_files(installed / "miassist")
    assert shipped == source, {"missing": source - shipped, "extra": shipped - source}


#: Run in a fresh interpreter: only the installed copy may answer ``import miassist``.
PROBE = r"""
import sys
site = sys.argv[1]
sys.path.insert(0, site)
import miassist
assert miassist.__file__.startswith(site), miassist.__file__
from importlib import resources

def walk(node, out):
    for child in node.iterdir():
        if child.is_dir():
            if child.name != "__pycache__":
                walk(child, out)
        elif not child.name.endswith(".py") and child.name != "py.typed":
            child.read_bytes()
            out.append(child.name)
    return out

read = walk(resources.files("miassist"), [])
from miassist.guidance.loader import Guidance
g = Guidance()
assert len(g.tools.tools) == 20 and g.explain and g.playbooks and g.instructions
from miassist.results.miserver_hints import load_hints
assert load_hints()
from miassist.web.pages import _text, environment
assert _text()
env = environment()
for name in ("base.html", "key.html", "new.html"):
    env.get_template(name)
from miassist.playbooks.registry import definitions_root
assert sorted(f.name for f in definitions_root().iterdir() if f.suffix == ".json")
from miassist.contracts import playbook, result_language
for name in ("annotation_rules.yaml", "error_text.yaml"):
    assert resources.files("miassist.contracts").joinpath(name).read_text(encoding="utf-8")
from miassist.app import create_app
from miassist.config import MiAssistSettings
settings = MiAssistSettings(
    apps="miworkbench,miserver,midataworks,miforge",
    miworkbench_url="http://127.0.0.1:9",
    miserver_url="http://127.0.0.1:9",
    midataworks_url="http://127.0.0.1:9",
    miforge_url="http://127.0.0.1:9",
)
create_app(settings)
print("loaded", len(read))
"""


def test_the_installed_copy_loads_every_runtime_data_file(installed: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", PROBE, str(installed)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    expected = len(_data_files(PACKAGE)) - 1  # py.typed is a marker, not data
    assert result.stdout.strip() == f"loaded {expected}", result.stdout
