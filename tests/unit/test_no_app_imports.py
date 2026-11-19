"""No module under ``src/`` imports an app's code (PADR ADR-001; Foundation task 1.5).

The suite's repositories sit side by side on one workstation, so ``import miserver`` resolves
locally and passes a manual review. miAssist reaches an app over its REST API, never its code.
The self-test proves the scanner sees each import form; with the forbidden list emptied, every
self-test case turns red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_scan import forbidden_imports

SRC = Path(__file__).resolve().parents[2] / "src"
FORBIDDEN = frozenset(
    {"src", "miserver", "millm", "mistudio", "midataworks", "miforge", "mcp_server", "api"}
)


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_tree_not_empty() -> None:
    assert python_files(), "nothing to scan; the guard would be vacuous"


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_module_imports_no_app(path: Path) -> None:
    hits = forbidden_imports(path.read_text(encoding="utf-8"), FORBIDDEN, str(path))
    assert not hits, f"{path.relative_to(SRC)} imports app code (ADR-001): {hits}"


SELF_TEST = [
    ("plain", "import miserver\n"),
    ("dotted", "import midataworks.services.x\n"),
    ("aliased", "import miforge as f\n"),
    ("from", "from mcp_server import tools\n"),
    ("from dotted", "from api.v1 import endpoints\n"),
    ("src root", "from src.core import config\n"),
    ("old names", "import millm\nimport mistudio\n"),
    ("importlib", "import importlib\nm = importlib.import_module('miserver.api')\n"),
    ("dunder", "m = __import__('midataworks')\n"),
    ("in function", "def f():\n    import miforge\n"),
    ("in try", "try:\n    import millm\nexcept ImportError:\n    pass\n"),
]


@pytest.mark.parametrize(("label", "source"), SELF_TEST, ids=[c[0] for c in SELF_TEST])
def test_scanner_sees_form(label: str, source: str) -> None:
    assert forbidden_imports(source, FORBIDDEN), f"the scanner missed the {label} form"


@pytest.mark.parametrize(
    "source",
    ["from . import x\n", "import miserverx\n", "import mcp\n", "URL = 'http://miserver:8000'\n"],
)
def test_scanner_allows(source: str) -> None:
    assert not forbidden_imports(source, FORBIDDEN)
