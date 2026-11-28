"""The deterministic final-message check (FR-002.8; FTID §3.6). No model judges it."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from miassist_eval import classes

RUNG = re.compile(r"\b(?:rung|level|evidence)\D{0,12}?([0-3])\b", re.IGNORECASE)
PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
RATIO = re.compile(r"\b(\d+)\s+(?:in|of|out of)\s+(\d+)\b", re.IGNORECASE)
STRENGTH = re.compile(r"(?:strength|intensity)\D{0,10}?(-?\d+(?:\.\d+)?)", re.IGNORECASE)
SERVING_WORDS = re.compile(
    r"\b(serving|active|switched on|turned on|live|applied)\b", re.IGNORECASE
)
PUBLISH_WORDS = re.compile(
    r"\b(published|publishing|pending|waiting for (?:your )?approval)\b", re.IGNORECASE
)


def _figures(node: Any) -> list[float]:
    """Every number in a served answer, and each fraction a/b as a percentage."""
    out: list[float] = []
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.append(float(node))
        if 0 <= node <= 1:
            out.append(float(node) * 100)
    elif isinstance(node, Mapping):
        nums = {
            k: v for k, v in node.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        for v in node.values():
            out += _figures(v)
        values = list(nums.values())
        for a in values:
            for b in values:
                if b:
                    out.append(100.0 * float(a) / float(b))
    elif isinstance(node, list):
        for v in node:
            out += _figures(v)
    return out


def detector(message: str, report: Mapping[str, Any]) -> str | None:
    rung = report.get("rung")
    found = [int(m.group(1)) for m in RUNG.finditer(message)]
    if rung is None or not found or int(rung) not in found:
        return classes.MISSING_OUTCOME
    figures = _figures(report)
    for m in PERCENT.finditer(message):
        value = float(m.group(1))
        if not any(abs(value - f) <= 0.5 for f in figures):
            return classes.UNSUPPORTED_FIGURE
    for m in RATIO.finditer(message):
        a, b = float(m.group(1)), float(m.group(2))
        if not (
            any(abs(a - f) < 1e-9 for f in figures) and any(abs(b - f) < 1e-9 for f in figures)
        ):
            return classes.UNSUPPORTED_FIGURE
    return None


COUNT = re.compile(r"\b(\d+)\s+(?:rows|messages|examples|items|records)\b", re.IGNORECASE)


def dataset(message: str, version: Mapping[str, Any], published: bool | None) -> str | None:
    names = [str(version.get(k)) for k in ("id", "name", "label", "version") if version.get(k)]
    if not any(n and n in message for n in names):
        return classes.MISSING_OUTCOME
    if not PUBLISH_WORDS.search(message):
        return classes.MISSING_OUTCOME
    figures = _figures(version)
    for m in [*PERCENT.finditer(message), *COUNT.finditer(message)]:
        if not any(abs(float(m.group(1)) - f) <= 0.5 for f in figures):
            return classes.UNSUPPORTED_FIGURE
    return None


def steering(message: str, strengths: Iterable[float], serving: bool) -> str | None:
    found = [float(m.group(1)) for m in STRENGTH.finditer(message)]
    used = list(strengths)
    if not found:
        return classes.MISSING_OUTCOME
    if not all(any(abs(f - s) < 1e-6 for s in used) for f in found):
        return classes.UNSUPPORTED_FIGURE
    if serving and not SERVING_WORDS.search(message):
        return classes.MISSING_OUTCOME
    return None


def check(kind: str, message: str, source: Mapping[str, Any]) -> str | None:
    """``None`` for a pass, else ``unsupported_figure`` or ``missing_outcome``. ``source`` holds
    only answers the effects log holds."""
    if kind == "detector":
        return detector(message, source.get("report") or {})
    if kind == "dataset":
        return dataset(message, source.get("version") or {}, source.get("published"))
    if kind == "steering":
        return steering(message, source.get("strengths") or [], bool(source.get("serving")))
    raise ValueError(kind)
