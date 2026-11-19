"""Guidance is data (PADR ADR-009; 001 FR-9, FR-10, FR-11; FTDD §4.4).

Every user-facing sentence lives in this package's YAML and Markdown files. ``Guidance.load()``
reads and validates them once, at start; a malformed file refuses start naming the file and the
path inside it. ``render`` is the one renderer: ``{slot}`` placeholders are filled, ``[[key]]``
glossary markers become the entry's term and are collected as ``terms``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MARKER: Final = re.compile(r"\[\[([a-z0-9-]+)\]\]")
SLOT: Final = re.compile(r"\{([a-z_]+)\}")
TOPICS: Final = ("start", "apps", "playbooks", "approvals", "results", "glossary", "connect")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GlossaryEntry(_Strict):
    key: str = Field(pattern=r"^[a-z0-9-]+$")
    term: str = Field(min_length=1)
    aliases: list[str] = []
    plain: str = Field(min_length=1)
    short: str = Field(min_length=1)
    good: str | None = None
    see_also: list[str] = []


class GlossaryFile(_Strict):
    version: int
    entries: list[GlossaryEntry]


class Outcome(_Strict):
    what_happened: str
    why_it_matters: str
    what_good_looks_like: str
    next_step: str


class ExplainFile(_Strict):
    version: int
    outcomes: dict[str, Outcome]


class AppText(_Strict):
    name: str
    purpose: str
    approvals_page: str


class AppsFile(_Strict):
    version: int
    apps: dict[str, AppText]


class ErrorFix(_Strict):
    fix: str


class AppErrorsFile(_Strict):
    version: int
    errors: dict[str, ErrorFix]


class ToolText(_Strict):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=1024)


class ToolsFile(_Strict):
    version: int
    tools: dict[str, ToolText]
    why: dict[str, str]


class HonestEndFile(_Strict):
    version: int
    one: str = Field(min_length=1)
    any_of: str = Field(min_length=1)
    joiner: str = Field(min_length=1)
    absent_answer: str = Field(min_length=1)
    unknown_playbook: str = Field(min_length=1)


class PlaybookTexts(_Strict):
    """``guidance/playbooks/<playbook id>.yaml``: the words of one playbook, by key (A25)."""

    version: int
    texts: dict[str, str]


class PlaybookFormsFile(_Strict):
    """The templates the three generated forms of a playbook are built from (FR-5)."""

    version: int
    guide_entry: str
    step_line: str
    step_skipped: str
    prompt: str
    skill: str
    expected_finished: str
    expected_next: str


class GuidanceError(SystemExit):
    """A malformed guidance file: start is refused, naming the file and the path inside it."""


def _yaml(root: Traversable, name: str, model: type[BaseModel]) -> Any:
    try:
        data = yaml.safe_load(root.joinpath(name).read_text(encoding="utf-8"))
        return model.model_validate(data)
    except ValidationError as exc:
        where = ".".join(str(p) for p in exc.errors()[0]["loc"])
        raise GuidanceError(
            f"guidance_invalid: {name} at {where}: {exc.errors()[0]['msg']}"
        ) from None
    except (OSError, yaml.YAMLError) as exc:
        raise GuidanceError(f"guidance_invalid: {name}: {type(exc).__name__}") from None


@dataclass(frozen=True)
class Rendered:
    text: str
    terms: tuple[str, ...]


class Guidance:
    """Every guidance file, loaded and validated once."""

    def __init__(self, root: Traversable | None = None) -> None:
        self.root = root or resources.files("miassist.guidance")
        glossary: GlossaryFile = _yaml(self.root, "glossary.yaml", GlossaryFile)
        self.glossary = {entry.key: entry for entry in glossary.entries}
        if len(self.glossary) != len(glossary.entries):
            raise GuidanceError("guidance_invalid: glossary.yaml repeats a key")
        self.apps: AppsFile = _yaml(self.root, "apps.yaml", AppsFile)
        self.app_errors: AppErrorsFile = _yaml(self.root, "app_errors.yaml", AppErrorsFile)
        self.tools: ToolsFile = _yaml(self.root, "tools.yaml", ToolsFile)
        self.jargon = [
            line.strip()
            for line in self.root.joinpath("jargon.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.explain: dict[str, ExplainFile] = {}
        for item in self.root.joinpath("explain").iterdir():
            if item.name.endswith(".yaml"):
                self.explain[item.name.removesuffix(".yaml")] = _yaml(
                    self.root.joinpath("explain"), item.name, ExplainFile
                )
        self.guide = {
            topic: self.root.joinpath("guide", f"{topic}.md").read_text(encoding="utf-8")
            for topic in TOPICS
        }
        self.instructions = self.root.joinpath("instructions.md").read_text(encoding="utf-8")
        self.honest_end: HonestEndFile = _yaml(self.root, "honest_end.yaml", HonestEndFile)
        self.playbook_forms: PlaybookFormsFile = _yaml(
            self.root, "playbook_forms.yaml", PlaybookFormsFile
        )
        self.playbooks: dict[str, PlaybookTexts] = {}
        folder = self.root.joinpath("playbooks")
        if folder.is_dir():
            for item in sorted(folder.iterdir(), key=lambda i: i.name):
                if item.name.endswith(".yaml"):
                    self.playbooks[item.name.removesuffix(".yaml")] = _yaml(
                        folder, item.name, PlaybookTexts
                    )
        self._check_markers()

    def all_texts(self) -> list[tuple[str, str]]:
        """``(where, text)`` for every renderable text (the marker and jargon checks)."""
        out = [(f"guide/{t}.md", text) for t, text in self.guide.items()]
        out.append(("instructions.md", self.instructions))
        for tool, file in self.explain.items():
            for outcome, texts in file.outcomes.items():
                for field, text in texts.model_dump().items():
                    out.append((f"explain/{tool}.yaml:{outcome}.{field}", text))
        for key, entry in self.glossary.items():
            out.append((f"glossary.yaml:{key}.plain", entry.plain))
        for pid, words in self.playbooks.items():
            for key, text in words.texts.items():
                out.append((f"playbooks/{pid}.yaml:{key}", text))
        return out

    def _check_markers(self) -> None:
        for where, text in self.all_texts():
            for key in MARKER.findall(text):
                if key not in self.glossary:
                    raise GuidanceError(
                        f"guidance_invalid: {where} marks [[{key}]], not in the glossary"
                    )
        for key, entry in self.glossary.items():
            for other in entry.see_also:
                if other not in self.glossary:
                    raise GuidanceError(
                        f"guidance_invalid: glossary.yaml:{key}.see_also names {other}"
                    )

    def app_name(self, app: str) -> str:
        return self.apps.apps[app].name

    def render(self, text: str, slots: dict[str, Any] | None = None) -> Rendered:
        """Fill ``{slot}``s (a missing slot is an error) and turn ``[[key]]`` into the term."""
        values = slots or {}

        def slot(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in values:
                raise KeyError(f"no value for the slot {{{name}}}")
            return str(values[name])

        terms: list[str] = []

        def marker(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in terms:
                terms.append(key)
            return self.glossary[key].term

        filled = SLOT.sub(slot, text)
        return Rendered(MARKER.sub(marker, filled), tuple(terms))

    def why(self, name: str, **slots: Any) -> str:
        """A next step's reason, from ``tools.yaml``."""
        return self.render(self.tools.why[name], slots).text

    def fix_for(self, code: str) -> str:
        entry = self.app_errors.errors.get(code)
        if entry is None and "." in code:
            entry = self.app_errors.errors.get("app_error")
        return entry.fix if entry else ""
