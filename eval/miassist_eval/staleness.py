"""Staleness against the reference, answer side and request side, and the reference's age
(FR-002.12, FR-002.12a; FTID §3.19; R1M-17; A31)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from miassist_eval import classes, openapi_ref
from miassist_eval.classes import Refusal

MAX_AGE_CEILING = 30


@dataclass
class Finding:
    stale: list[str] = field(default_factory=list)
    drift: dict[str, str] = field(default_factory=dict)  # app -> "none" | "compatible"


def check_request(
    doc: openapi_ref.RefDoc, route: openapi_ref.Route, request: Mapping[str, Any]
) -> list[str]:
    """Path params and query against ``parameters``; body against ``requestBody`` (C-17)."""
    return openapi_ref.validate_request(
        doc, route, str(request["path"]), dict(request.get("query") or {}), request.get("body")
    )


def check_cassette(
    cassette: Mapping[str, Any],
    refs: Mapping[str, openapi_ref.RefDoc],
    recorded_hashes: Mapping[str, str],
) -> Finding:
    """Every record: its route exists, its answer and its request validate. A recorded hash that
    differs while everything validates is ``drift: compatible``."""
    out = Finding()
    for record in cassette.get("records", []):
        app = record["app"]
        req = record["request"]
        doc = refs.get(app)
        if doc is None:
            out.stale.append(f"{app}: no reference document")
            continue
        route = openapi_ref.resolve(doc, req["method"], req["path"])
        if route is None or route.template != req["route"]:
            out.stale.append(f"{app} {req['method']} {req['route']}: absent from the reference")
            continue
        answer = record["answer"]
        for p in openapi_ref.validate_answer(doc, route, int(answer["status"]), answer.get("body")):
            out.stale.append(f"{app} {route.key} {p}")
        for p in check_request(doc, route, req):
            out.stale.append(f"{app} {route.key} {p}")
    for app, digest in recorded_hashes.items():
        if app in refs:
            out.drift[app] = "none" if refs[app].sha256 == digest else "compatible"
    return out


def refuse_if_stale(finding: Finding) -> None:
    if finding.stale:
        raise Refusal(classes.CASSETTE_STALE, "; ".join(finding.stale[:10]))


def max_age_days() -> int:
    raw = os.environ.get("MIASSIST_EVAL_REF_MAX_AGE_DAYS", str(MAX_AGE_CEILING))
    value = int(raw)
    if value > MAX_AGE_CEILING:
        raise Refusal(
            classes.REFERENCE_TOO_OLD, f"MIASSIST_EVAL_REF_MAX_AGE_DAYS={value} is above 30"
        )
    return value


def age_mode() -> str:
    mode = os.environ.get("MIASSIST_EVAL_REF_AGE_MODE", "warn")
    if mode not in ("warn", "fail"):
        raise ValueError(f"MIASSIST_EVAL_REF_AGE_MODE must be warn or fail, not {mode!r}")
    return mode


def check_age(doc: openapi_ref.RefDoc, now: datetime, max_days: int) -> str | None:
    days = openapi_ref.age_days(doc, now)
    if days > max_days:
        return f"{classes.REFERENCE_TOO_OLD}: {doc.app} {days} days"
    return None


def apply_age(findings: list[str], mode: str, warn: Any = print) -> bool:
    """Mode ``warn``: print ``WARNING`` lines and return True (every record ``reference_stale``).
    Mode ``fail``: refuse ``reference_too_old``. No findings: False."""
    if not findings:
        return False
    if mode == "fail":
        raise Refusal(classes.REFERENCE_TOO_OLD, "; ".join(findings))
    for f in findings:
        warn(f"WARNING {f}")
    return True
