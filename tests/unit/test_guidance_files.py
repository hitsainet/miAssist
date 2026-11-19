"""Guidance text is data (001 FR-11; FTASKS 8.1, 8.5).

``test_no_long_literals_in_code`` is a ratchet with an EMPTY allow-list (AC-11.1): no module under
``src/miassist/tools/``, ``results/`` or ``playbooks/`` holds a string literal over 60 characters
with a space in it, except a docstring, a log message or an error code. The words a person reads
live in ``src/miassist/guidance/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("src/miassist/tools", "src/miassist/results", "src/miassist/playbooks")
LIMIT = 60
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})
LOGGER_NAMES = frozenset({"_log", "log", "logger", "_logger", "logging"})
#: The ratchet's allow-list. It starts empty and must stay empty: move a sentence to guidance/.
ALLOWED: frozenset[tuple[str, str]] = frozenset()


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def _log_args(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in LOGGER_NAMES
            and node.args
        ):
            for sub in ast.walk(node.args[0]):
                out.add(id(sub))
    return out


def long_literals(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """``(line, text)`` for every offending literal; an f-string counts its literal parts."""
    tree = ast.parse(source, filename=filename)
    skip = _docstrings(tree) | _log_args(tree)
    hits: list[tuple[int, str]] = []
    inside_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and id(node) not in skip:
            parts = "".join(
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            inside_fstring |= {id(v) for v in node.values}
            if len(parts) > LIMIT and " " in parts:
                hits.append((node.lineno, parts))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and id(node) not in inside_fstring
            and len(node.value) > LIMIT
            and " " in node.value
        ):
            hits.append((node.lineno, node.value))
    return hits


def test_no_long_literals_in_code() -> None:
    found = []
    for folder in SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            rel = str(path.relative_to(ROOT))
            for line, text in long_literals(path.read_text(encoding="utf-8"), rel):
                if (rel, text) not in ALLOWED:
                    found.append(f"{rel}:{line}: {text[:70]!r}")
    assert found == [], "move these sentences to src/miassist/guidance/:\n" + "\n".join(found)
    assert ALLOWED == frozenset()


SENTENCE = "this sentence is written straight into the code instead of guidance data"


@pytest.mark.parametrize(
    "source,expected",
    [
        (f"x = {SENTENCE!r}\n", 1),
        (f"def f(a):\n    return f'{SENTENCE} {{a}}'\n", 1),
        (f'def f():\n    """{SENTENCE}"""\n', 0),
        (f"_log.warning({SENTENCE!r})\n", 0),
        ("x = 'short words only'\n", 0),
        ("x = '" + "a" * 80 + "'\n", 0),
    ],
    ids=["literal", "fstring", "docstring", "log", "short", "no-space"],
)
def test_scanner_self_test(source: str, expected: int) -> None:
    assert len(long_literals(source)) == expected


def test_scanned_folders_exist() -> None:
    for folder in SCANNED:
        assert any((ROOT / folder).rglob("*.py")), folder


# -- 8.1: a malformed guidance file refuses start, naming the file and the path (AC-11.2) -------

GUIDANCE = ROOT / "src/miassist/guidance"


def _copy(tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "guidance"
    shutil.copytree(GUIDANCE, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target


@pytest.mark.parametrize(
    "file,old,new,named",
    [
        ("apps.yaml", "approvals_page:", "approvals_pages:", "apps.yaml at apps."),
        ("tools.yaml", "version: 1", "version: one", "tools.yaml at version"),
        ("glossary.yaml", "key: auroc", "key: AUROC!", "glossary.yaml at entries."),
        ("explain/miassist_guide.yaml", "next_step:", "next_steps:", "miassist_guide.yaml at "),
    ],
    ids=["extra-field", "wrong-type", "bad-key", "explain"],
)
def test_bad_file_refuses(tmp_path: Path, file: str, old: str, new: str, named: str) -> None:
    from miassist.guidance.loader import Guidance, GuidanceError

    root = _copy(tmp_path)
    target = root / file
    text = target.read_text(encoding="utf-8")
    assert old in text, (file, old)
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(GuidanceError) as refused:
        Guidance(root)
    assert str(refused.value).startswith("guidance_invalid: ")
    assert named in str(refused.value)


def test_unknown_marker_refuses(tmp_path: Path) -> None:
    from miassist.guidance.loader import Guidance, GuidanceError

    root = _copy(tmp_path)
    target = root / "guide" / "start.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n[[no-such-term]]\n", "utf-8")
    with pytest.raises(GuidanceError, match=r"guide/start.md marks \[\[no-such-term\]\]"):
        Guidance(root)


def test_unmodified_copy_loads(tmp_path: Path) -> None:
    from miassist.guidance.loader import Guidance

    assert Guidance(_copy(tmp_path)).glossary
