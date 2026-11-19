"""``canonical_payload()`` reproduces every vendored per-route vector (001 FTASKS 5.2a; A29, A38;
R3M-1). The vectors are miWorkbench 045's (``docs/schemas/miworkbench-approval-payload-vectors-v1
.json``): for each gated route, the request an agent sends and the flat payload the operator
approves. A list body is keyed by the handler's parameter name, read from the vector's payload."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from miassist.adapters.miworkbench import canonical_payload
from tests.support.vectors import VECTORS_FILE, VECTORS_VENDORED

pytestmark = pytest.mark.skipif(
    not VECTORS_VENDORED, reason="001-V has not vendored 045's per-route vectors yet (V-4)"
)
VECTORS: list[dict[str, Any]] = (
    json.loads(VECTORS_FILE.read_text())["vectors"] if VECTORS_VENDORED else []
)
_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def path_params(template: str, path: str) -> dict[str, str]:
    parts = _PARAM.split(template)
    pattern = "".join(
        re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^/]+)" for i, p in enumerate(parts)
    )
    match = re.fullmatch(pattern, path)
    assert match, (template, path)
    return match.groupdict()


def reproduce(vector: dict[str, Any]) -> dict[str, Any]:
    request = vector["request"]
    params = path_params(vector["route"], request["path"])
    body = request["body"]
    body_param = None
    if body is not None and not isinstance(body, dict):
        known = {"_method", "_route", *params, *request["query"]}
        (body_param,) = [k for k in vector["payload"] if k not in known]
    return canonical_payload(
        vector["method"], vector["route"], params, request["query"], body, body_param=body_param
    )


def test_every_gated_route_has_one_vector() -> None:
    assert len(VECTORS) >= 40
    keys = [(v["method"], v["route"]) for v in VECTORS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("vector", VECTORS, ids=[f"{v['row']}-{v['action']}" for v in VECTORS])
def test_vectors(vector: dict[str, Any]) -> None:
    assert reproduce(vector) == vector["payload"]
