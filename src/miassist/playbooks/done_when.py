"""``evaluate_done_when``: Core's one implementation of a step's ``done_when`` (001 FR-13; FPRD
§5.2.2). Every status provider (003-005) calls it; none re-derives it.

``exists``: the pointer resolves. ``truthy``: it resolves to a value Python treats as true.
``equals``: it resolves and equals ``value`` (JSON equality: a boolean is never a number).
``in``: it resolves to a member of the array ``value``. ``gte``: it resolves to a number (not a
boolean) at least ``value``. A pointer that does not resolve, a malformed pointer or a type
mismatch is ``False``, never an exception.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

_MISSING: Final = object()
_INDEX: Final = re.compile(r"^(0|[1-9][0-9]*)$")


def resolve(data: Any, pointer: str) -> Any:
    """RFC 6901: the value ``pointer`` names in ``data``, or ``_MISSING``."""
    if pointer == "":
        return data
    if not pointer.startswith("/"):
        return _MISSING
    node = data
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            if not _INDEX.match(token) or int(token) >= len(node):
                return _MISSING
            node = node[int(token)]
        else:
            return _MISSING
    return node


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def json_equal(a: Any, b: Any) -> bool:
    """Equality as JSON sees it: ``true`` is not ``1``; ``1`` equals ``1.0``."""
    if _number(a) and _number(b):
        return bool(a == b)
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and bool(a == b)


def evaluate_done_when(predicate: Any, data: Any) -> bool:
    """Whether ``predicate`` (a ``done_when`` model or mapping) holds on ``data``."""
    try:
        get = predicate.get if isinstance(predicate, Mapping) else predicate.__getattribute__
        pointer, op = get("pointer"), get("op")
        value = get("value") if isinstance(predicate, Mapping) else predicate.value
        if not isinstance(pointer, str):
            return False
        found = resolve(data, pointer)
        if found is _MISSING:
            return False
        if op == "exists":
            return True
        if op == "truthy":
            return bool(found)
        if op == "equals":
            return json_equal(found, value)
        if op == "in":
            return isinstance(value, list) and any(json_equal(found, v) for v in value)
        if op == "gte":
            return _number(found) and _number(value) and found >= value
        return False
    except Exception:  # a predicate never raises (FPRD §5.2.2)
        return False
