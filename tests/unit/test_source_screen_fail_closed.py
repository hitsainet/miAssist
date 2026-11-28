"""R3 review fixes (OR3-001-3, OR3-001-6), 2026-11-16: the miDataworks source screen's fail-closed
branches (OVN-miassist-core-32).

- A source check the app does not answer (502/503/504, a timeout, the app gone) stops the call:
  nothing is sent (``base.py`` step 3b's ``return stopped``; mutation M3-13 survived round 3).
- A source id named in the QUERY is checked like one in the body (M3-3 survived round 3).
- A value under a ``*source_id`` / ``*source_ids`` key in any shape other than a string / a list of
  strings (a repeated query parameter, a string under ``*_ids``, a number) is refused, never skipped.
- A source answer with no ``gated`` key is unknown, so not showable.

The reviewer's proposed test (``proposed_test_source_screen_r3.py``) is the first two tests.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from miassist.adapters.base import Unavailable
from miassist.adapters.midataworks import named_source_ids, showable
from miassist.errors import MiAssistError
from tests.unit.test_source_credentials import build_body, call, fake


def _answer_for_stored(answer: Any) -> Any:
    def handler(request: Any) -> Any:
        if request.path_params["source_id"] == "src-stored":
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {"id": "src-open", "token_tier": "none", "gated": None}

    return handler


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_an_unanswered_source_check_sends_nothing(status: int) -> None:
    app = fake()
    app.on(
        "GET",
        "/api/v1/sources/{source_id}",
        _answer_for_stored(httpx.Response(status, text="bad gateway")),
    )
    answer = await call(
        app, "midataworks.fixture_build_version", json=build_body("src-open", "src-stored")
    )
    assert isinstance(answer, Unavailable), answer
    assert app.calls("POST") == [], "the build was sent with an unchecked source"
    assert len(app.calls("GET", "/api/v1/sources/{source_id}")) == 2


@pytest.mark.parametrize(
    "exc",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("refused")],
    ids=["timeout", "connection-refused"],
)
async def test_a_source_check_that_times_out_sends_nothing(exc: Exception) -> None:
    app = fake()
    app.on("GET", "/api/v1/sources/{source_id}", _answer_for_stored(exc))
    answer = await call(
        app, "midataworks.fixture_build_version", json=build_body("src-open", "src-stored")
    )
    assert isinstance(answer, Unavailable), answer
    assert answer.reason == (
        "timeout" if isinstance(exc, httpx.TimeoutException) else "connection refused"
    )
    assert app.calls("POST") == [], "the build was sent with an unchecked source"


async def test_a_source_id_in_the_query_is_checked() -> None:
    app = fake()
    with pytest.raises(MiAssistError) as caught:
        await call(
            app,
            "midataworks.fixture_build_version",
            json=build_body("src-open"),
            params={"source_id": "src-stored"},
        )
    assert caught.value.code == "source_needs_operator"
    assert app.calls("POST") == []
    checked = [r.path_params["source_id"] for r in app.calls("GET", "/api/v1/sources/{source_id}")]
    assert checked == ["src-open", "src-stored"]


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("params", {"source_id": ["src-open", "src-stored"]}),  # a repeated query parameter
        ("params", {"benchmark_source_ids": "src-stored"}),
        ("json", {"source_id": 7}),
        ("json", {"inputs": [{"kind": "source", "source_id": ["src-stored"]}]}),
        ("json", {"benchmark_source_ids": ["src-open", 7]}),
        ("json", {"benchmark_source_ids": {"id": "src-stored"}}),
    ],
    ids=["query-list", "ids-string", "id-number", "nested-list", "ids-number", "ids-mapping"],
)
async def test_a_source_id_in_an_unexpected_shape_is_refused(
    where: str, value: dict[str, Any]
) -> None:
    app = fake()
    kwargs: dict[str, Any] = {"json": build_body("src-open")}
    if where == "params":
        kwargs["params"] = value
    else:
        kwargs["json"] = {**build_body("src-open"), **value}
    with pytest.raises(MiAssistError) as caught:
        await call(app, "midataworks.fixture_build_version", **kwargs)
    assert caught.value.code == "source_unchecked"
    assert app.calls("POST") == []


def test_a_null_source_id_names_nothing() -> None:
    assert named_source_ids({"source_id": None, "benchmark_source_ids": None}) == []
    assert named_source_ids({"inputs": [{"source_id": "a"}], "x_source_ids": ["b", "c"]}) == [
        "a",
        "b",
        "c",
    ]


@pytest.mark.parametrize(
    "source",
    [
        {"token_tier": "none"},  # no gated key: unknown
        {"token_tier": "none", "gated": 0},
        {"token_tier": "none", "gated": "False "},
        {"token_tier": "none", "gated": "auto"},
    ],
    ids=["gated-missing", "gated-zero", "gated-odd-string", "gated-auto"],
)
def test_an_unknown_gated_value_is_not_showable(source: dict[str, Any]) -> None:
    assert not showable(source)
    for ok in (None, "false", False):
        assert showable({"token_tier": "none", "gated": ok}), ok
