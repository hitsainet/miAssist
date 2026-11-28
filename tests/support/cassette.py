"""``miassist.cassette/v1``: the one cassette format, its root and its fake transport (001 FR-31;
A22, M14; FTID §8.3; FTASKS 4.5).

- The format is the Pydantic model ``Cassette``; its JSON Schema is written to
  ``tests/fixtures/miassist-cassette-v1.schema.json`` (``write_schema``), the default of
  ``MIASSIST_CORE_CASSETTE_SCHEMA`` that 002 reads. ``tests/unit/test_cassette_root.py`` pins the
  file to the model.
- The ONE root is ``tests/fixtures/cassettes/private/`` (stripped from the public mirror); nothing
  writes a cassette anywhere else (``CassetteRoot.target``).
- Headers are stripped on both sides: a request keeps only its agent header, the approval-id
  header and the route's fixed headers; an answer keeps only the approval headers.
- ``CassetteTransport`` serves records in ``seq`` order per (app, route template); a request that
  does not match the next record, or has none left, raises ``CassetteMiss``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from miassist.adapters.base import APPROVAL_ID_HEADER, HEADERS

FORMAT = "miassist.cassette/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "tests/fixtures/cassettes/private"
SCHEMA_FILE = REPO_ROOT / "tests/fixtures/miassist-cassette-v1.schema.json"
ANSWER_HEADERS = frozenset({"x-mistudio-approval", "x-millm-approval"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CassetteRequest(_Strict):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(description="The request path as sent.")
    route: str = Field(description="The route template the path matched.")
    query: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None


class CassetteAnswer(_Strict):
    status: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None


class CassetteRecord(_Strict):
    seq: int = Field(ge=0)
    app: Literal["miworkbench", "miserver", "midataworks", "miforge"]
    app_version: str
    time: str = Field(description="When it was recorded, ISO 8601 with offset.")
    request: CassetteRequest
    answer: CassetteAnswer


class Cassette(_Strict):
    """One recorded (or hand-written) exchange with fake apps."""

    format: Literal["miassist.cassette/v1"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,119}$")
    source: Literal["recorded", "hand_written"]
    records: list[CassetteRecord]


def schema() -> dict[str, Any]:
    out = Cassette.model_json_schema()
    out["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    out["$id"] = "miassist-cassette-v1.schema.json"
    return out


def schema_text() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True) + "\n"


def write_schema(target: Path = SCHEMA_FILE) -> None:
    target.write_text(schema_text(), encoding="utf-8")


def strip_request_headers(
    app: str, headers: Mapping[str, str], fixed: Iterable[str] = ()
) -> dict[str, str]:
    keep = {HEADERS[app][0].lower(), APPROVAL_ID_HEADER.lower(), *(h.lower() for h in fixed)}
    return {k: v for k, v in headers.items() if k.lower() in keep}


def strip_answer_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() in ANSWER_HEADERS}


class CassetteMiss(AssertionError):
    """A request the cassette does not hold next."""


class CassetteRoot:
    """The one place cassettes are written."""

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()

    def target(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.name.endswith(".cassette.json"):
            raise ValueError(f"cassette_outside_root: {relative}")
        return path


def load(path: Path) -> Cassette:
    return Cassette.model_validate_json(path.read_text(encoding="utf-8"))


class CassetteTransport(httpx.MockTransport):
    """Serve one app's records in ``seq`` order per route template."""

    def __init__(self, cassette: Cassette, app: str, templates: Iterable[str]) -> None:
        self.app = app
        self.queues: dict[str, list[CassetteRecord]] = {}
        for record in sorted(cassette.records, key=lambda r: r.seq):
            if record.app == app:
                self.queues.setdefault(record.request.route, []).append(record)
        self.templates = list(templates)
        super().__init__(self.serve)

    def _template(self, path: str) -> str | None:
        from miassist_fixtures.filter import RouteProfile

        for template in self.templates:
            if RouteProfile(template).path_params(path) is not None:
                return template
        return None

    def serve(self, request: httpx.Request) -> httpx.Response:
        template = self._template(request.url.path)
        queue = self.queues.get(template or "", [])
        if not queue:
            raise CassetteMiss(f"no record left for {request.method} {request.url.path}")
        record = queue[0]
        body = json.loads(request.content) if request.content else None
        query = dict(request.url.params)
        expected = record.request
        if (request.method, request.url.path, query, body) != (
            expected.method,
            expected.path,
            expected.query,
            expected.body,
        ):
            raise CassetteMiss(f"{request.method} {request.url.path} is not record {record.seq}")
        queue.pop(0)
        return httpx.Response(
            record.answer.status, json=record.answer.body, headers=record.answer.headers
        )
