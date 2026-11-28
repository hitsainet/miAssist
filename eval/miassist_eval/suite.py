"""A suite: the plan, the start path, the runs (FR-002.15, FR-002.21, FR-002.22; FTDD §5.1, §7;
FTID §1, §7.3).

The start path is: the CI refusal of paid tiers (M13), the driver registry (FR-002.18/19 wiring),
the reference age (FR-002.12a), then **lint, integrity and staleness, in that order, once each**
(``tests/wiring/test_suite_start_path.py``). A refusal on the start path records zero runs.
Each run gets its own replay state, listeners, tap and run id; artifacts are hashed into the record.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from miassist_eval import (
    __version__,
    budget,
    cassette,
    classes,
    goals,
    gpu_guard,
    lint,
    openapi_ref,
    replay,
    score,
    shapes,
    staleness,
)
from miassist_eval import drivers as drivers_pkg
from miassist_eval.canonical import sha256_file
from miassist_eval.classes import Refusal
from miassist_eval.clock import Clock
from miassist_eval.drivers.scripted import Step
from miassist_eval.edge import Edge
from miassist_eval.servers import Listener, serve
from miassist_eval.tap import Tap

EVAL_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = EVAL_ROOT / "runs"
MAX_ATTEMPTS = 3  # one attempt plus up to two re-attempts of an invalid run (FR-002.21)

#: ``async (app_urls) -> (mcp_url, stop)``: starts the server under test against the listeners.
SutFactory = Callable[[Mapping[str, str]], Awaitable[tuple[str, Callable[[], Awaitable[None]]]]]


@dataclass
class Plan:
    tier: str
    surface: str
    client: str
    goal_ids: list[str]
    phrasings: list[str] = field(default_factory=lambda: ["a"])
    runs: int = 1
    takes: dict[str, Path] = field(default_factory=dict)
    steps: dict[str, list[Step]] = field(default_factory=dict)
    budget_usd: float | None = None
    suite_id: str = field(default_factory=lambda: "s-" + uuid.uuid4().hex[:12])


@dataclass
class SuiteResult:
    suite_id: str
    refused: Refusal | None
    records: list[dict[str, Any]]
    out_dir: Path


@dataclass
class Suite:
    plan: Plan
    sut: SutFactory
    refs: Mapping[str, openapi_ref.RefDoc]
    profiles: Mapping[str, Mapping[str, Any]]
    goal_set: goals.GoalSet
    runs_dir: Path = RUNS_DIR
    index: list[dict[str, Any]] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    say: Callable[[str], None] = print
    registry: Mapping[str, Any] = field(default_factory=lambda: drivers_pkg.REGISTRY)
    glossary: Sequence[str] = field(default_factory=lint.glossary_terms)
    _takes: dict[str, cassette.Take] = field(default_factory=dict)
    _gpu: gpu_guard.GpuList = field(default_factory=dict)
    _reference_stale: bool = False

    @property
    def out_dir(self) -> Path:
        return self.runs_dir / self.plan.suite_id

    # ------------------------------------------------------------------ the start path
    async def start(self) -> None:
        budget.refuse_paid_in_ci(self.plan.tier)
        if self.plan.client not in self.registry:
            raise Refusal(classes.DRIVER_NOT_REGISTERED, self.plan.client)
        self._gpu = gpu_guard.load(
            self.refs["miworkbench"], self.profiles["miworkbench"].get("gpu_arms")
        )
        for goal_id in self.plan.goal_ids:
            # R1 review fix (OR1-002-4), 2026-11-16: a goal whose GPU starts the vendored vectors
            # do not guard yet is refused on the miAssist surface (zero runs), never skipped.
            gpu_guard.refuse_incomplete_goal(
                str(self.goal_set.goal(goal_id).get("playbook_id")), self._gpu, self.plan.surface
            )
        max_days = staleness.max_age_days()
        ages = []
        for app, doc in sorted(self.refs.items()):
            days = openapi_ref.age_days(doc, self.now())
            self.say(f"reference {app}: {days} days old ({doc.source})")
            found = staleness.check_age(doc, self.now(), max_days)
            if found:
                ages.append(found)
        self._reference_stale = staleness.apply_age(ages, staleness.age_mode(), self.say)
        tools = await self.live_tools()
        findings = lint.lint(
            [self.goal_set.goal(g) for g in self.plan.goal_ids],
            self.goal_set.fixed_replies,
            tools,
            self.glossary if self.plan.surface == "miassist" else [],
            lint.jargon(),
        )
        if findings:
            raise Refusal(classes.LINT_REFUSED, "; ".join(str(f) for f in findings))
        for goal_id in self.plan.goal_ids:
            self._takes[goal_id] = cassette.load(self.plan.takes[goal_id], self.index)
        for take in self._takes.values():
            hashes = {a: v["openapi_sha256"] for a, v in take.manifest["apps"].items()}
            found_stale = staleness.check_cassette(take.cassette, self.refs, hashes)
            staleness.refuse_if_stale(found_stale)
            take.manifest["_drift"] = found_stale.drift

    async def live_tools(self) -> list[str]:
        """The live ``tools/list`` of the server under test, started on an empty replay."""
        edge = self.edge()
        rep = replay.Replay(edge=edge, library={}, health={})
        listeners = [await serve(rep.app_for(app)) for app in self.refs]
        try:
            url, stop = await self.sut(
                {a: lis.url for a, lis in zip(self.refs, listeners, strict=True)}
            )
            try:
                from mcp import Client

                async with Client(url) as client:
                    return [t.name for t in (await client.list_tools()).tools]
            finally:
                await stop()
        finally:
            for lis in listeners:
                await lis.stop()

    def edge(self) -> Edge:
        return Edge(
            surface=self.plan.surface, refs=self.refs, profiles=self.profiles, gpu=self._gpu
        )

    # ------------------------------------------------------------------ runs
    async def run(self) -> SuiteResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self.start()
        except Refusal as refusal:
            self._write_suite([], refusal)
            self.say(f"REFUSED {refusal}")
            return SuiteResult(self.plan.suite_id, refusal, [], self.out_dir)
        records: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        for goal_id in self.plan.goal_ids:
            for phrasing in self.plan.phrasings:
                for _ in range(self.plan.runs):
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        record = await self.one_run(goal_id, phrasing, attempt, len(attempts))
                        attempts.append(
                            {
                                "run_id": record["run_id"],
                                "goal": goal_id,
                                "attempt": attempt,
                                "outcome": record["outcome"],
                                "cls": record["cls"],
                            }
                        )
                        records.append(record)
                        self._write_suite(attempts, None)
                        if record["outcome"] != classes.INVALID:
                            break
        return SuiteResult(self.plan.suite_id, None, records, self.out_dir)

    def _write_suite(self, attempts: list[dict[str, Any]], refusal: Refusal | None) -> None:
        doc = {
            "suite_id": self.plan.suite_id,
            "tier": self.plan.tier,
            "surface": self.plan.surface,
            "client": self.plan.client,
            "goals": self.plan.goal_ids,
            "attempts": attempts,
            "refused": None if refusal is None else {"cls": refusal.cls, "detail": refusal.detail},
        }
        (self.out_dir / "suite.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")

    async def one_run(
        self, goal_id: str, phrasing: str, attempt: int, order: int
    ) -> dict[str, Any]:
        run_id = "r-" + uuid.uuid4().hex[:12]
        run_dir = self.out_dir / run_id
        run_dir.mkdir(parents=True)
        goal = self.goal_set.goal(goal_id)
        take = self._takes[goal_id]
        clock = Clock()
        health = {}
        for app in self.refs:
            hp = take.path / "health" / f"{app}.json"
            if hp.is_file():
                health[app] = json.loads(hp.read_text())
        rep = replay.build(take.cassette, self.edge(), health, clock)
        listeners: list[Listener] = []
        infra: str | None = None
        transcript: dict[str, Any] = {"tools": [], "calls": []}
        tap = Tap(upstream="", clock=clock)
        start = clock.mono()
        try:
            for app in self.refs:
                listeners.append(await serve(rep.app_for(app)))
            control = await serve(rep.control_app())
            listeners.append(control)
            app_urls = {a: lis.url for a, lis in zip(self.refs, listeners, strict=False)}
            url, stop = await self.sut(app_urls)
            base, _, path = url.partition("//")[2].partition("/")
            tap.upstream = f"http://{base}"
            tap_listener = await serve(tap.app())
            listeners.append(tap_listener)
            try:
                transcript = await self.drive(
                    f"{tap_listener.url}/{path}", goal_id, rep, control.url
                )
            finally:
                await stop()
        except Exception as exc:  # noqa: BLE001 - every harness fault is a named invalid cause
            infra = classes.HARNESS_ERROR
            transcript["error"] = repr(exc)
        finally:
            for lis in reversed(listeners):
                await lis.stop()
        end = clock.mono()
        if infra is None and tap.count() != len(transcript["calls"]):
            infra = classes.COUNT_MISMATCH
        return self._score(
            run_id,
            run_dir,
            goal,
            phrasing,
            attempt,
            order,
            take,
            rep,
            tap,
            transcript,
            infra,
            start,
            end,
            clock,
        )

    async def drive(
        self, url: str, goal_id: str, rep: replay.Replay, control_url: str
    ) -> dict[str, Any]:
        """Tier 1a: the scripted path, releasing each pending approval (the fixed "approved"
        reply) before the next step (FR-002.20)."""
        from mcp import Client

        steps = self.plan.steps.get(goal_id, [])
        transcript: dict[str, Any] = {"tools": [], "calls": []}
        async with Client(url) as client, httpx.AsyncClient(base_url=control_url) as control:
            transcript["tools"] = [t.name for t in (await client.list_tools()).tools]
            for step in steps:
                for app, approval_id in self._pending(rep):
                    await control.post(f"/release/{app}/{approval_id}")
                result = await client.call_tool(step.tool, step.arguments)
                text = "".join(getattr(c, "text", "") for c in result.content)
                transcript["calls"].append(
                    {
                        "shape_errors": shapes.check(
                            self.plan.surface,
                            result.structured_content,
                            bool(result.is_error),
                            text,
                        ),
                        "tool": step.tool,
                        "arguments": step.arguments,
                        "is_error": bool(result.is_error),
                        "text": "".join(getattr(c, "text", "") for c in result.content),
                    }
                )
        return transcript

    def _pending(self, rep: replay.Replay) -> list[tuple[str, str]]:
        out = []
        for line in rep.state.effects.lines:
            entry = cassette.route_entry(
                self.profiles.get(str(line.get("app")), {}),
                str(line.get("method")),
                str(line.get("route")),
            )
            if entry and entry.get("poll_of") == "approval":
                state = replay._get(line.get("answer"), entry.get("state_field", "status"))
                approval_id = str(line.get("path", "")).rstrip("/").rsplit("/", 1)[-1]
                if (
                    state in entry.get("open_states", [])
                    and (line["app"], approval_id) not in rep.state.released
                ):
                    out.append((str(line["app"]), approval_id))
        return out

    def _score(
        self,
        run_id: str,
        run_dir: Path,
        goal: Mapping[str, Any],
        phrasing: str,
        attempt: int,
        order: int,
        take: cassette.Take,
        rep: replay.Replay,
        tap: Tap,
        transcript: dict[str, Any],
        infra: str | None,
        start: float,
        end: float,
        clock: Clock,
    ) -> dict[str, Any]:
        (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=1, default=str))
        with (run_dir / "tap.jsonl").open("w") as fh:
            for line in tap.log:
                fh.write(json.dumps(line, sort_keys=True, default=str) + "\n")
        rep.state.effects.write(run_dir / "effects.jsonl")
        (run_dir / "clock.json").write_text(
            json.dumps({"start": start, "end": end, **clock.stamp()})
        )
        artifacts = {
            name: {"path": fname, "sha256": sha256_file(run_dir / fname)}
            for name, fname in (
                ("transcript", "transcript.json"),
                ("tap_log", "tap.jsonl"),
                ("effects_log", "effects.jsonl"),
                ("clock", "clock.json"),
            )
        }
        driver = self.registry[self.plan.client]()
        info = driver.preflight({})
        drift = take.manifest.get("_drift", {})
        meta = {
            "schema": "miassist.eval-run/v1",
            "run_id": run_id,
            "suite_id": self.plan.suite_id,
            "attempt": attempt,
            "surface": self.plan.surface,
            "tier": self.plan.tier,
            "client": {"name": info.name, "version": info.version},
            "model": {
                "requested": info.model_requested,
                "served": info.model_served,
                "mismatch": info.model_requested != info.model_served,
            },
            "server_under_test": {"kind": self.plan.surface},
            "apps": {
                a: {
                    "version": v["version"],
                    "openapi_sha256": v["openapi_sha256"],
                    "drift": drift.get(a, "none"),
                    "reference_age_days": openapi_ref.age_days(self.refs[a], self.now()),
                }
                for a, v in take.manifest["apps"].items()
            },
            "harness_version": __version__,
            "cassette": {"id": take.cassette_id, "manifest_sha256": take.manifest_sha256},
            "goal": {
                "id": goal["id"],
                "phrasing": phrasing,
                "goal_set_sha256": self.goal_set.sha256,
            },
            "tokens": {
                "input": None,
                "output": None,
                "cache_read": None,
                "cache_write": None,
                "reported": {
                    "input": False,
                    "output": False,
                    "cache_read": False,
                    "cache_write": False,
                },
                "null_reason": {"all": "tier 1a has no model"},
            },
            "user_nudges": 0,
            "reference_stale": self._reference_stale,
            "artifacts": artifacts,
            "time": {"start": start, "end": end},
            "infra": infra,
            "failures": rep.state.failures,
            "step_errors": sum(1 for c in transcript.get("calls", []) if c.get("is_error")),
            "shape_errors": sum(
                len(c.get("shape_errors", [])) for c in transcript.get("calls", [])
            ),
            "operator_handoffs": rep.state.handoffs,
            "expected_path": [s.tool for s in self.plan.steps.get(goal["id"], [])],
            "limits": {"wall_s": 1800, "turns": 80},
        }
        record = score.build_record(meta, run_dir, goal, self.profiles)
        record["attempt_order"] = order
        (run_dir / "record.json").write_text(
            json.dumps(record, indent=1, sort_keys=True, default=str)
        )
        self.say(
            f"{run_id} {goal['id']}/{phrasing} attempt {attempt}: {record['outcome']} "
            f"{record['cls'] or ''}"
        )
        return record
