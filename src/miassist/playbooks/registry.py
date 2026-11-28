"""The playbook registry (001 FR-5, AC-5.1, AC-5.2, AC-5.7, AC-5.8; FTID §3.8; A7, A25).

``load`` reads every definition under ``playbooks/definitions/``, validates it against
``mistudio.playbook/v1`` (the Pydantic models the published schema is generated from, plus the
three constraints the models carry only as schema text: an ``entry`` step, unique step ids,
``done_when.value`` iff the operator needs one), and resolves EVERY text key from
``guidance/playbooks/<id>.yaml`` (A25): an unresolved key refuses start naming the file, the field
and the key; resolved lengths are checked against FPRD §5.2's bounds. A step whose apps
(``requires_apps``, read as any-of; absent means the playbook's own list) are none of them
installed is skipped; a step that is not skipped must name a tool registered in this deployment.
A playbook is OFFERED iff one of its apps is installed and one of its ``entry`` steps runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from pydantic import ValidationError

from miassist.contracts.playbook import TEXT_BOUNDS, DoneWhen, Playbook
from miassist.guidance.loader import Guidance

APP_ORDER = ("miworkbench", "miserver", "midataworks", "miforge")


class PlaybookError(SystemExit):
    """A definition that cannot be offered safely: start is refused, naming file, field and key."""


@dataclass(frozen=True)
class ResolvedStep:
    id: str
    tool: str
    title: str
    explain_beginner: str
    explain_expert: str
    done_when: DoneWhen
    done_description: str
    args: Mapping[str, Any]
    entry: bool
    waits_for: tuple[str, ...]
    apps: tuple[str, ...]
    skipped: bool


@dataclass(frozen=True)
class ResolvedPlaybook:
    """A definition with its words resolved, for this installation."""

    id: str
    version: int
    title: str
    goal: str
    requires_apps: tuple[str, ...]
    steps: tuple[ResolvedStep, ...]
    offered: bool
    needs: tuple[str, ...]
    terms: tuple[str, ...]
    source: str

    @property
    def runnable(self) -> tuple[ResolvedStep, ...]:
        return tuple(s for s in self.steps if not s.skipped)

    @property
    def first_step(self) -> ResolvedStep:
        return next(s for s in self.steps if s.entry and not s.skipped)

    @property
    def not_in_this_installation(self) -> list[str]:
        return [s.id for s in self.steps if s.skipped]


@dataclass
class PlaybookRegistry:
    """Every shipped definition, resolved; ``offered`` is this installation's offer, sorted by id."""

    playbooks: dict[str, ResolvedPlaybook] = field(default_factory=dict)

    @property
    def offered(self) -> list[ResolvedPlaybook]:
        return [p for _, p in sorted(self.playbooks.items()) if p.offered]

    def get(self, playbook_id: str) -> ResolvedPlaybook | None:
        return self.playbooks.get(playbook_id)


def _sorted_apps(apps: Iterable[str]) -> tuple[str, ...]:
    wanted = set(apps)
    return tuple(a for a in APP_ORDER if a in wanted)


class _Resolver:
    def __init__(self, guidance: Guidance, playbook_id: str, source: str) -> None:
        self.guidance = guidance
        self.source = source
        self.file = f"guidance/playbooks/{playbook_id}.yaml"
        texts = guidance.playbooks.get(playbook_id)
        if texts is None:
            raise PlaybookError(f"playbook_invalid: {source}: no words file {self.file}")
        self.texts = texts.texts
        self.terms: list[str] = []

    def __call__(self, key: str, where: str, bound: str) -> str:
        if key not in self.texts:
            raise PlaybookError(
                f"playbook_invalid: {self.source} at {where}: the key {key!r} is not in {self.file}"
            )
        try:
            rendered = self.guidance.render(self.texts[key])
        except KeyError as exc:
            raise PlaybookError(f"playbook_invalid: {self.file} at {key}: {exc.args[0]}") from None
        low, high = TEXT_BOUNDS[bound]
        if not low <= len(rendered.text) <= high:
            raise PlaybookError(
                f"playbook_invalid: {self.file} at {key}: {len(rendered.text)} characters, "
                f"outside {low}-{high} for {bound}"
            )
        self.terms += [t for t in rendered.terms if t not in self.terms]
        return rendered.text


def _validate(raw: Any, source: str) -> Playbook:
    try:
        playbook = Playbook.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise PlaybookError(f"playbook_invalid: {source} at {where}: {first['msg']}") from None
    if not any(step.entry for step in playbook.steps):
        raise PlaybookError(f"playbook_invalid: {source} at steps: no step has entry: true")
    seen: set[str] = set()
    for i, step in enumerate(playbook.steps):
        if step.id in seen:
            raise PlaybookError(f"playbook_invalid: {source} at steps.{i}.id: repeats {step.id!r}")
        seen.add(step.id)
        needs_value = step.done_when.op in ("equals", "in", "gte")
        has_value = "value" in step.done_when.model_fields_set
        if needs_value != has_value:
            raise PlaybookError(
                f"playbook_invalid: {source} at steps.{i}.done_when.value: "
                + ("required" if needs_value else "not allowed")
                + f" for op {step.done_when.op!r}"
            )
    return playbook


def resolve(
    playbook: Playbook,
    guidance: Guidance,
    installed: frozenset[str],
    tool_names: frozenset[str],
    source: str,
) -> ResolvedPlaybook:
    text = _Resolver(guidance, playbook.id, source)
    steps: list[ResolvedStep] = []
    for i, step in enumerate(playbook.steps):
        apps = _sorted_apps(step.requires_apps or playbook.requires_apps)
        skipped = not (set(apps) & installed)
        tool = step.tool.root
        if not skipped and tool not in tool_names:
            raise PlaybookError(
                f"playbook_invalid: {source} at steps.{i}.tool: {tool!r} is not registered here"
            )
        where = f"steps.{i}"
        steps.append(
            ResolvedStep(
                id=step.id,
                tool=tool,
                title=(
                    text(step.title.root, f"{where}.title", "step.title") if step.title else step.id
                ),
                explain_beginner=text(
                    step.explain_beginner.root, f"{where}.explain_beginner", "explain_beginner"
                ),
                explain_expert=text(
                    step.explain_expert.root, f"{where}.explain_expert", "explain_expert"
                ),
                done_when=step.done_when,
                done_description=text(
                    step.done_when.description.root,
                    f"{where}.done_when.description",
                    "done_when.description",
                ),
                args=dict(step.args or {}),
                entry=step.entry,
                waits_for=tuple(str(w) for w in step.waits_for or ()),
                apps=apps,
                skipped=skipped,
            )
        )
    title = text(playbook.title.root, "title", "title")
    goal = text(playbook.goal.root, "goal", "goal")
    pb_apps = _sorted_apps(playbook.requires_apps)
    entry_runs = any(s.entry and not s.skipped for s in steps)
    offered = bool(set(pb_apps) & installed) and entry_runs
    if offered:
        needs: tuple[str, ...] = ()
    else:
        entry_apps = {a for s in steps if s.entry for a in s.apps}
        needs = _sorted_apps((set(pb_apps) | entry_apps) - installed)
    return ResolvedPlaybook(
        id=playbook.id,
        version=playbook.version,
        title=title,
        goal=goal,
        requires_apps=pb_apps,
        steps=tuple(steps),
        offered=offered,
        needs=needs,
        terms=tuple(text.terms),
        source=source,
    )


def definitions_root() -> Traversable:
    return resources.files("miassist.playbooks").joinpath("definitions")


def load(
    guidance: Guidance,
    installed: Iterable[str],
    tool_names: Iterable[str],
    definitions: Traversable | None = None,
) -> PlaybookRegistry:
    """Every definition under ``definitions`` (default: the shipped directory), resolved for this
    installation. Refuses start on any invalid definition."""
    root = definitions if definitions is not None else definitions_root()
    have = frozenset(installed)
    tools = frozenset(tool_names)
    registry = PlaybookRegistry()
    files: Sequence[Traversable] = sorted(
        (f for f in root.iterdir() if f.name.endswith(".json")), key=lambda f: f.name
    )
    for item in files:
        source = f"playbooks/definitions/{item.name}"
        try:
            raw = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PlaybookError(f"playbook_invalid: {source}: {type(exc).__name__}") from None
        playbook = _validate(raw, source)
        if item.name != f"{playbook.id}.json":
            raise PlaybookError(
                f"playbook_invalid: {source} at id: the file must be {playbook.id}.json"
            )
        if playbook.id in registry.playbooks:
            raise PlaybookError(f"playbook_invalid: {source} at id: repeats {playbook.id!r}")
        registry.playbooks[playbook.id] = resolve(playbook, guidance, have, tools, source)
    return registry
