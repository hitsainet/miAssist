"""The hint lint (FR-002.5; FTID §7.1). A refusal names the goal, the phrasing and the text."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from miassist_eval.readability import fk_grade

EVAL_ROOT = Path(__file__).resolve().parents[1]
JARGON_PATH = EVAL_ROOT / "baseline_jargon.txt"
GLOSSARY_PATH = EVAL_ROOT.parent / "src" / "miassist" / "guidance" / "glossary.yaml"
APP_NAMES = re.compile(
    r"\b(miWorkbench|miServer|miDataworks|miForge|miAssist|miLLM|miSuite)\b", re.IGNORECASE
)
IDENTIFIERS = [
    re.compile(r"\bm_[0-9a-f]{6,}\b"),
    re.compile(r"\bpmr?_\w+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE),
    re.compile(r"@\d"),
]
STEPS = re.compile(r"^\s*(\d+[.)]|[-*•])\s", re.MULTILINE)
MAX_CHARS = 600
MAX_GRADE = 9.0
#: Tool names under four characters are skipped only when they are English stop words; the skipped
#: names are listed by the lint so the skip is visible (FTID §7.1).
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "go",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "no",
        "of",
        "on",
        "or",
        "so",
        "the",
        "to",
        "up",
        "us",
        "we",
        "all",
        "any",
        "can",
        "get",
        "has",
        "how",
        "new",
        "not",
        "now",
        "one",
        "our",
        "out",
        "run",
        "see",
        "set",
        "use",
        "was",
        "who",
        "why",
        "you",
    }
)


@dataclass(frozen=True)
class Finding:
    rule: str
    goal: str
    phrasing: str
    text: str

    def __str__(self) -> str:
        return f"{self.rule}: goal {self.goal} phrasing {self.phrasing}: {self.text!r}"


def _term_pattern(term: str) -> re.Pattern[str]:
    words = r"[\s_-]+".join(re.escape(w) for w in re.split(r"[\s_]+", term.strip()))
    return re.compile(rf"\b{words}(s|es)?\b", re.IGNORECASE)


def jargon(path: Path = JARGON_PATH) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def glossary_terms(path: Path = GLOSSARY_PATH) -> list[str]:
    """Core's glossary ``term`` values (read as data; never an import of the server package).
    Aliases are not terms (OVN-miassist-eval-5): "model", "version", "level" are everyday words."""
    if not path.is_file():
        return []
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(e["term"]) for e in data.get("entries", [])]


def skipped_tool_names(tool_names: Iterable[str]) -> list[str]:
    return sorted(n for n in tool_names if len(n) < 4 and n.lower() in STOP_WORDS)


def check_text(
    goal: str,
    phrasing: str,
    text: str,
    tool_names: Iterable[str],
    terms: Iterable[str],
) -> list[Finding]:
    out: list[Finding] = []
    skip = set(skipped_tool_names(tool_names))
    for name in tool_names:
        if name in skip:
            continue
        for variant in {name, name.replace("_", " ")}:
            m = re.search(rf"\b{re.escape(variant)}\b", text, re.IGNORECASE)
            if m:
                out.append(Finding("tool_name", goal, phrasing, m.group(0)))
                break
    for term in terms:
        m = _term_pattern(term).search(text)
        if m:
            out.append(Finding("glossary_term", goal, phrasing, m.group(0)))
    for m in APP_NAMES.finditer(text):
        out.append(Finding("app_name", goal, phrasing, m.group(0)))
    for pattern in IDENTIFIERS:
        m = pattern.search(text)
        if m:
            out.append(Finding("identifier", goal, phrasing, m.group(0)))
    m = STEPS.search(text)
    if m:
        out.append(Finding("steps", goal, phrasing, m.group(0).strip()))
    if len(text) > MAX_CHARS:
        out.append(Finding("length", goal, phrasing, f"{len(text)} characters"))
    grade = fk_grade(text)
    if grade > MAX_GRADE:
        out.append(Finding("readability", goal, phrasing, f"grade {grade:.1f}"))
    return out


def lint(
    goals: list[dict[str, Any]],
    fixed_replies: dict[str, str],
    live_tool_names: Iterable[str],
    glossary: Iterable[str],
    jargon_terms: Iterable[str],
) -> list[Finding]:
    tools = list(live_tool_names)
    terms = [*glossary, *jargon_terms]
    out: list[Finding] = []
    for g in goals:
        for key, text in g["phrasings"].items():
            out += check_text(g["id"], key, text, tools, terms)
    for key, text in fixed_replies.items():
        out += check_text("fixed_replies", key, text, tools, terms)
    return out
