"""The replay server: each app's REST API from a take (FR-002.9, FR-002.11, FR-002.11a, FR-002.11c,
FR-002.20; FTDD §5.2; FTID §3.3; TD-6, TD-10).

One Starlette app per app listener, a shared ``RunState``, and a control app (127.0.0.1 only, never
given to the server under test) with ``POST /release/{app}/{approval_id}`` and
``POST /release-handoff/{app}``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route as StarletteRoute

from miassist_eval import cassette as cassette_mod
from miassist_eval import classes, openapi_ref
from miassist_eval.clock import Clock
from miassist_eval.edge import Edge
from miassist_eval.effects import EffectsLog

#: Status reads the replay holds at their recorded "before" value until the operator's hand-off is
#: answered by the "done" reply (FR-002.11c).
HANDOFF_HELD = frozenset(
    {("miserver", "GET", "/api/probes/status"), ("miserver", "GET", "/api/clusters")}
)


@dataclass
class RunState:
    cursors: dict[Any, int] = field(default_factory=dict)
    released: set[tuple[str, str]] = field(default_factory=set)
    handoffs_released: set[str] = field(default_factory=set)
    effects: EffectsLog = field(default_factory=EffectsLog)
    failures: list[tuple[str, str]] = field(default_factory=list)
    handoffs: int = 0
    requests: dict[str, int] = field(default_factory=dict)


def _get(obj: Any, dotted: str) -> Any:
    node = obj
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: obj}


def _replace(node: Any, old: str, new: str) -> Any:
    if isinstance(node, str):
        return node.replace(old, new) if old else node
    if isinstance(node, list):
        return [_replace(v, old, new) for v in node]
    if isinstance(node, dict):
        return {k: _replace(v, old, new) for k, v in node.items()}
    return node


@dataclass
class Replay:
    edge: Edge
    library: dict[Any, list[dict[str, Any]]]
    health: Mapping[str, Any]
    clock: Clock = field(default_factory=Clock)
    state: RunState = field(default_factory=RunState)

    # ------------------------------------------------------------------ helpers
    def _entry(self, app: str, method: str, template: str) -> dict[str, Any] | None:
        return cassette_mod.route_entry(self.edge.profiles[app], method, template)

    def _hold_index(
        self,
        app: str,
        method: str,
        template: str,
        path: str,
        seq: list[dict[str, Any]],
        entry: dict[str, Any] | None,
    ) -> int | None:
        if entry and entry.get("poll_of") == "approval":
            approval_id = path.rstrip("/").rsplit("/", 1)[-1]
            if (app, approval_id) in self.state.released:
                return None
            field_name = entry.get("state_field", "status")
            open_states = entry.get("open_states", [])
            opens = [
                i
                for i, r in enumerate(seq)
                if _get(r["answer"].get("body"), field_name) in open_states
            ]
            return opens[-1] if opens else None
        if (app, method, template) in HANDOFF_HELD and app not in self.state.handoffs_released:
            first = seq[0]["answer"].get("body")
            last = 0
            for i in range(1, len(seq)):
                if seq[i]["answer"].get("body") != first:
                    break
                last = i
            return last
        return None

    def _nearest(self, key: Any) -> tuple[Any, list[str]]:
        app, method, template, _params, values = key
        mine = _flatten(json.loads(values))
        best: tuple[Any, list[str]] | None = None
        for other in self.library:
            if other[:3] != (app, method, template):
                continue
            theirs = _flatten(json.loads(other[4]))
            differs = sorted(k for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k))
            if dict(other[3]) != dict(key[3]):
                differs = ["path", *differs]
            if best is None or len(differs) < len(best[1]):
                best = (other, differs)
        return best if best is not None else (None, [])

    def _echo(
        self,
        request: Mapping[str, Any],
        recorded: Mapping[str, Any],
        entry: dict[str, Any] | None,
        body: Any,
    ) -> tuple[Any, list[str]]:
        echoed = []
        for dotted in (entry or {}).get("echo", []):
            new, old = _get(request, dotted), _get(recorded, dotted)
            if isinstance(new, str) and isinstance(old, str) and new != old:
                body = _replace(body, old, new)
                echoed.append(dotted)
        return body, echoed

    # ------------------------------------------------------------------ the one handler
    def handle(
        self,
        app: str,
        method: str,
        path: str,
        query: Mapping[str, Any],
        headers: Mapping[str, str],
        body: Any,
    ) -> tuple[int, dict[str, str], Any]:
        self.state.requests[app] = self.state.requests.get(app, 0) + 1
        t = self.clock.mono()
        line: dict[str, Any] = {
            "t_mono": t,
            "app": app,
            "method": method,
            "path": path,
            "query": dict(query),
            "request_body": body,
        }
        if method == "GET" and path == "/openapi.json":
            return 200, {}, self.edge.refs[app].openapi
        if method == "GET" and path == "/api/health" and app in self.health:
            return 200, {}, self.health[app]
        route, verdict = self.edge.check(app, method, path, query, headers, body)
        line["route"] = route.template if route else None
        if verdict is not None:
            if verdict.cls == classes.OPERATOR_HANDOFF:
                self.state.handoffs += 1
            else:
                self.state.failures.append((verdict.cls, f"{method} {path}"))
            self.state.effects.append(
                **line, status=verdict.status, refused=verdict.cls, answer=verdict.body
            )
            return verdict.status, {}, verdict.body
        assert route is not None
        entry = self._entry(app, method, route.template)
        request = {"query": dict(query), "body": body}
        key = (
            app,
            method,
            route.template,
            frozenset(route.params(path).items()),
            cassette_mod.match_values(
                request,
                entry,
                list(self.edge.profiles[app].get("default_match", ["query", "body"])),
            ),
        )
        seq = self.library.get(key)
        if not seq:
            nearest, differs = self._nearest(key)
            payload = {
                "cassette_miss": {
                    "route": route.key,
                    "differs": differs,
                    "nearest": None if nearest is None else str(nearest[4]),
                }
            }
            self.state.failures.append((classes.OFF_RECORDING, f"{method} {path}: {differs}"))
            self.state.effects.append(
                **line, status=503, refused=classes.OFF_RECORDING, answer=payload
            )
            return 503, {}, payload
        i = self.state.cursors.get(key, 0)
        hold = self._hold_index(app, method, route.template, path, seq, entry)
        if hold is not None:
            i = min(i, hold)
        record = seq[min(i, len(seq) - 1)]
        self.state.cursors[key] = i + 1
        answer = record["answer"]
        out_body, echoed = self._echo(
            request,
            {"query": record["request"].get("query") or {}, "body": record["request"].get("body")},
            entry,
            copy.deepcopy(answer.get("body")),
        )
        status = int(answer["status"])
        answer_headers = dict(answer.get("headers") or {})
        drift = self.edge.observe(
            app, route, method, path, query, headers, body, status, answer_headers, out_body
        )
        if drift:
            self.state.failures.append((drift, route.key))
        self.state.effects.append(
            **line,
            status=status,
            answer=out_body,
            matched_key=str(key[4]),
            echoes=echoed,
            sequence_index=min(i, len(seq) - 1),
        )
        return status, answer_headers, out_body

    # ------------------------------------------------------------------ ASGI
    def app_for(self, app: str) -> Starlette:
        async def endpoint(request: Request) -> Response:
            raw = await request.body()
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode("utf-8", "replace")
            status, headers, out = self.handle(
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

    def control_app(self) -> Starlette:
        async def release(request: Request) -> Response:
            self.state.released.add(
                (request.path_params["app"], request.path_params["approval_id"])
            )
            return JSONResponse({"released": True})

        async def release_handoff(request: Request) -> Response:
            self.state.handoffs_released.add(request.path_params["app"])
            self.state.effects.append(
                t_mono=self.clock.mono(), app=request.path_params["app"], handoff_done=True
            )
            return JSONResponse({"released": True})

        return Starlette(
            routes=[
                StarletteRoute("/release/{app}/{approval_id}", release, methods=["POST"]),
                StarletteRoute("/release-handoff/{app}", release_handoff, methods=["POST"]),
            ]
        )


def build(
    take_cassette: Mapping[str, Any],
    edge: Edge,
    health: Mapping[str, Any],
    clock: Clock | None = None,
) -> Replay:
    lib = cassette_mod.library(
        take_cassette, lambda a, m, p: openapi_ref.resolve(edge.refs[a], m, p), edge.profiles
    )
    return Replay(edge=edge, library=lib, health=health, clock=clock or Clock())
