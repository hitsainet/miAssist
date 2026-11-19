"""The recorder: pass-through between the server under test and the live apps (FR-002.10,
FR-002.11, FR-002.11a-c, FR-002.14b-d; FTDD §5.3; A22, A37; TD-11, TD-13).

Per request: the edge checks (resolve, decision block, serving changes, the GPU guard with the
baseline's terminal hold, the agent header); Core's request-time fixture check BEFORE forwarding;
forward with stripped credentials; filter a list answer BEFORE it is passed on or written; refuse
an answer that still carries a non-fixture value (``foreign_id``) or is text (``text_answer_refused``)
and NEVER grow the allowed set from an answer (R1 review fix OR1-002-2, OVN-miassist-eval-20); then,
in a recording run only, append the record to the take. A tier-2 run passes
through the same recorder with ``writing`` off and writes nothing under the cassette root (A37).

Nothing here runs against a live app in CI or tonight: ``record`` is by hand on the workstation.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route as StarletteRoute

from miassist_eval import allowed, classes
from miassist_eval import cassette as cassette_mod
from miassist_eval.classes import Refusal
from miassist_eval.clock import Clock
from miassist_eval.edge import Edge
from miassist_eval.effects import EffectsLog

STRIP = ("authorization", "cookie", "set-cookie")
STRIP_WORDS = ("token", "key", "secret")
#: Forward: ``(app, method, path, query, headers, body) -> (status, headers, body)``.
Forward = Callable[
    [str, str, str, Mapping[str, Any], Mapping[str, str], Any],
    Awaitable[tuple[int, dict[str, str], Any]],
]


def strip_credentials(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in STRIP
        and not any(w in k.lower() for w in STRIP_WORDS)
        and k.lower() not in ("host", "content-length", "transfer-encoding", "connection")
    }


@dataclass
class Recorder:
    edge: Edge
    forward: Forward
    allowed_set: Any
    app_versions: Mapping[str, str]
    writing: bool
    clock: Clock = field(default_factory=Clock)
    effects: EffectsLog = field(default_factory=EffectsLog)
    records: list[dict[str, Any]] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    handoffs: int = 0
    gap_only: bool = False

    def __post_init__(self) -> None:
        allowed.require_core()  # filter_module_missing, whatever MIASSIST_REQUIRE_CORE says (R3M-4)

    async def handle(
        self,
        app: str,
        method: str,
        path: str,
        query: Mapping[str, Any],
        headers: Mapping[str, str],
        body: Any,
    ) -> tuple[int, dict[str, str], Any]:
        t = self.clock.mono()
        line: dict[str, Any] = {
            "t_mono": t,
            "app": app,
            "method": method,
            "path": path,
            "query": dict(query),
            "request_body": body,
        }
        if self.gap_only and method != "GET":
            raise Refusal(classes.HARNESS_ERROR, f"gap recording refuses {method} (FR-002.10)")
        route, verdict = self.edge.check(app, method, path, query, headers, body)
        line["route"] = route.template if route else None
        if verdict is not None:
            if verdict.cls == classes.OPERATOR_HANDOFF:
                self.handoffs += 1
            else:
                self.failures.append((verdict.cls, f"{method} {path}"))
            self.effects.append(
                **line, status=verdict.status, refused=verdict.cls, answer=verdict.body
            )
            return verdict.status, {}, verdict.body
        assert route is not None
        entry = cassette_mod.route_entry(self.edge.profiles[app], method, route.template)
        try:
            self.allowed_set.check_request(
                allowed.core_profile(entry, route.template),
                {"path": path, "query": dict(query), "body": body},
            )
        except allowed.FixtureRefused as exc:
            refusal = {"refused": classes.FIXTURE_NOT_ALLOWED, "at": exc.where}
            self.failures.append((classes.FIXTURE_NOT_ALLOWED, f"{method} {path} {exc.where}"))
            self.effects.append(
                **line, status=403, refused=classes.FIXTURE_NOT_ALLOWED, answer=refusal
            )
            return 403, {}, refusal
        status, answer_headers, answer = await self.forward(
            app, method, path, query, strip_credentials(headers), body
        )
        try:
            answer, dropped = allowed.filter_answer(entry, answer, self.allowed_set)
        except allowed.UnfilteredList:
            refusal = {"refused": classes.UNFILTERED_LIST, "route": route.key}
            self.failures.append((classes.UNFILTERED_LIST, route.key))
            self.effects.append(**line, status=502, refused=classes.UNFILTERED_LIST, answer=refusal)
            return 502, {}, refusal
        # R1 review fix (OR1-002-2), 2026-11-16, OVN-miassist-eval-20 reversing OVN-7: the recorder
        # NEVER adds an id from an answer to the allowed set (allowed ids are fixture ids only), and
        # an answer still carrying a non-fixture value after the list filter is refused: never
        # recorded, never passed to the server under test (and so never to a hosted model).
        if isinstance(answer, (str, bytes)) and answer not in ("", b""):
            # R1 review fix (OR1-002-7): a text answer cannot be scanned field by field.
            return self._refuse(line, classes.TEXT_ANSWER_REFUSED, route.key, 502)
        foreign = allowed.answer_findings(answer, self.allowed_set)
        if foreign:
            return self._refuse(line, classes.FOREIGN_ID, route.key, 502, foreign[:5])
        drift = self.edge.observe(
            app, route, method, path, query, headers, body, status, answer_headers, answer
        )
        if drift:
            self.failures.append((drift, route.key))
        kept_headers = cassette_mod.strip_headers(answer_headers, cassette_mod.ANSWER_HEADERS)
        if self.writing:
            self.records.append(
                {
                    "seq": len(self.records),
                    "app": app,
                    "app_version": str(self.app_versions.get(app, "")),
                    "time": datetime.now(UTC).isoformat(),
                    "request": {
                        "method": method,
                        "path": path,
                        "route": route.template,
                        "query": {k: str(v) for k, v in query.items()},
                        "headers": cassette_mod.strip_headers(
                            headers, cassette_mod.REQUEST_HEADERS
                        ),
                        "body": body,
                    },
                    "answer": {"status": status, "headers": kept_headers, "body": answer},
                }
            )
        self.effects.append(**line, status=status, answer=answer, dropped=dropped)
        return status, kept_headers, answer

    def _refuse(
        self, line: dict[str, Any], cls: str, key: str, status: int, at: Any = None
    ) -> tuple[int, dict[str, str], Any]:
        refusal: dict[str, Any] = {"refused": cls, "route": key}
        if at is not None:
            refusal["at"] = at
        self.failures.append((cls, key))
        self.effects.append(**line, status=status, refused=cls, answer=refusal)
        return status, {}, refusal

    def cassette(self, name: str) -> dict[str, Any]:
        """The take's cassette in Core's format; refused on any stray id (the last pass)."""
        if not self.writing:
            raise Refusal(classes.HARNESS_ERROR, "a tier-2 run writes no cassette (A37)")
        doc = {
            "format": cassette_mod.FORMAT,
            "name": name,
            "source": "recorded",
            "records": self.records,
        }
        stray = allowed.take_findings(doc, self.allowed_set)
        if stray:
            raise Refusal(classes.FIXTURE_NOT_ALLOWED, f"stray ids in the take: {stray[:5]}")
        return doc

    def app_for(self, app: str) -> Starlette:
        async def endpoint(request: Request) -> Response:
            raw = await request.body()
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode("utf-8", "replace")
            status, headers, out = await self.handle(
                app,
                request.method,
                request.url.path,
                dict(request.query_params),
                dict(request.headers),
                body,
            )
            return JSONResponse(out, status_code=status, headers=headers)

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        return Starlette(routes=[StarletteRoute("/{path:path}", endpoint, methods=methods)])


def httpx_forward(base_urls: Mapping[str, str]) -> Forward:  # pragma: no cover - live only
    import httpx

    async def forward(
        app: str,
        method: str,
        path: str,
        query: Mapping[str, Any],
        headers: Mapping[str, str],
        body: Any,
    ) -> tuple[int, dict[str, str], Any]:
        async with httpx.AsyncClient(base_url=base_urls[app], timeout=60) as client:
            resp = await client.request(
                method,
                path,
                params=dict(query),
                headers=dict(headers),
                json=body if body is not None else None,
            )
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            return resp.status_code, dict(resp.headers), payload

    return forward


def tty_hold(tty_path: str = "/dev/tty") -> Callable[[Any, Any], bool]:
    """FR-002.11b: ask the operator on the controlling terminal; no terminal refuses."""

    def hold(start: Any, req: Any) -> bool:
        prompt = (
            f"\nGPU start {start.method} {start.template} ({start.action}). "
            "Allow it once? [y/N] "
        )
        try:
            with open(tty_path, "a", encoding="utf-8") as out:
                out.write(prompt)
            with open(tty_path, encoding="utf-8") as inp:
                return inp.readline().strip().lower() == "y"
        except OSError:
            return False

    return hold
