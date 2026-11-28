"""Shared AST import scanning for the structural guards (ADR-001, ADR-006).

Kept as plain functions over a string so each guard's self-test can prove the scanner sees every
import form: a scanner that can only run over the real tree cannot be proven to see anything.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

DYNAMIC_IMPORTERS = frozenset({"import_module", "__import__"})


def _root(dotted: str) -> str:
    return dotted.split(".", 1)[0]


def imported_roots(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """``(lineno, dotted_name)`` for every absolute import in ``source``: ``import x``,
    ``import x.y as z``, ``from x import y``, ``importlib.import_module("x")``,
    ``__import__("x")``, at any depth (functions, ``try``, ``if``)."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise AssertionError(f"{filename} does not parse: {exc}") from exc
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                hits.append((node.lineno, node.module))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None
            )
            if name in DYNAMIC_IMPORTERS:
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        hits.append((node.lineno, arg.value))
    return hits


def forbidden_imports(
    source: str, forbidden: Iterable[str], filename: str = "<string>"
) -> list[tuple[int, str]]:
    """The imports in ``source`` whose top-level package is in ``forbidden``."""
    roots = frozenset(forbidden)
    return [(line, name) for line, name in imported_roots(source, filename) if _root(name) in roots]
