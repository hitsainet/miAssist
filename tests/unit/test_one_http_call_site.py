"""``httpx`` is imported by exactly one module, ``src/miassist/adapters/base.py`` (PADR ADR-006;
Foundation task 1.6). Every app call goes through it, so the agent header, the route registry and
the gate classes cannot be bypassed by a second client.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_scan import forbidden_imports

SRC = Path(__file__).resolve().parents[2] / "src"
ALLOWED = {Path("miassist/adapters/base.py")}


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_only_base_imports_httpx(path: Path) -> None:
    if path.relative_to(SRC) in ALLOWED:
        return
    hits = forbidden_imports(path.read_text(encoding="utf-8"), {"httpx"}, str(path))
    assert not hits, f"{path.relative_to(SRC)} imports httpx; only adapters/base.py may (ADR-006)"


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\n",
        "from httpx import AsyncClient\n",
        "import httpx as h\n",
        "def f():\n    import httpx\n",
        "import importlib\nimportlib.import_module('httpx')\n",
    ],
)
def test_scanner_sees_form(source: str) -> None:
    assert forbidden_imports(source, {"httpx"})
