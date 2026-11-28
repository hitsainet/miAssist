"""Mapping an app's HTTP answer (001 FR-17; FTDD §5.3).

| Answer | Result |
|---|---|
| 2xx (not 202) | ``Resource`` |
| 202 carrying ``approval`` or ``approval_id`` (miServer: inside ``data``) | ``Pending`` (a wait; A19) |
| 202 without one (``BuildAccepted``, ``ImportAccepted``) | ``Resource`` (an accepted job) |
| miDataworks ``import_confirmation_required`` | ``Handoff`` (the operator's large import; A24) |
| the app's error envelope | ``AppError`` with the code normalised for line 1 (A30) |
| 502/503/504 without the envelope | ``Unavailable`` |
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from miassist.adapters.base import (
    AppAnswer,
    AppError,
    GateClass,
    Handoff,
    Pending,
    RawAnswer,
    Resource,
    Route,
    Unavailable,
)
from miassist.errors import ERROR_CODE_MAX, valid_code
from miassist.results.approvals import Style, approval_object

_log = logging.getLogger("miassist.app_answers")
HANDOFF_CODES: Final = frozenset({"import_confirmation_required"})


def normalise_code(app: str, code: str | None) -> str:
    """``<app>.<code>`` in the line-1 form: lower case, ``[a-z0-9_]``; ``<app>.app_error`` when the
    app's code is empty or would not fit (A30)."""
    norm = re.sub(r"[^a-z0-9_]+", "_", (code or "").lower()).strip("_")
    norm = re.sub(r"_+", "_", norm)
    if norm and not norm[0].isalpha():
        norm = "e_" + norm
    full = f"{app}.{norm}"
    if not norm or len(full) > ERROR_CODE_MAX or not valid_code(full):
        return f"{app}.app_error"
    return full


def _envelope(app: str, body: Any) -> tuple[str | None, str] | None:
    """``(code, message)`` from the app's error envelope, or ``None`` when there is none."""
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict) and ("code" in error or "message" in error):
        return (str(error.get("code") or "") or None, str(error.get("message") or ""))
    detail = body.get("detail")
    if app == "miworkbench" and detail is not None:
        if isinstance(detail, dict):
            return (str(detail.get("code") or "") or None, str(detail.get("message") or ""))
        if isinstance(detail, str):
            return (None, detail)
        return (None, "")
    return None


def _has_approval(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    if "approval" in body or "approval_id" in body:
        return True
    data = body.get("data")
    return isinstance(data, dict) and ("approval" in data or "approval_id" in data)


def classify(app: str, route: Route, raw: RawAnswer) -> AppAnswer:
    if raw.status == 202 and _has_approval(raw.json):
        if route.file_first or raw.headers.get("x-mistudio-approval") == "pending":
            _log.warning("a miWorkbench route answered a no-id 202; miAssist files first (A32)")
        style: Style = (
            "file_first" if app == "miworkbench" and route.file_first else "server_executed"
        )
        summary = str((raw.json or {}).get("summary") or (raw.json or {}).get("message") or "")
        return Pending(app, approval_object(app, raw.json, style=style, summary=summary or "-"))
    if 200 <= raw.status < 300:
        return Resource(app, raw.status, raw.json)
    envelope = _envelope(app, raw.json)
    if envelope is None:
        if raw.status in (502, 503, 504):
            return Unavailable(app, f"HTTP {raw.status}")
        return AppError(app, raw.status, normalise_code(app, f"http_{raw.status}"), "", raw.text)
    code, message = envelope
    if code in HANDOFF_CODES:
        return Handoff(app, code or "operator_action")
    if code is None:
        # miWorkbench's own request parsing answers 422 with no code (L-4).
        code = (
            "invalid_body" if app == "miworkbench" and raw.status == 422 else f"http_{raw.status}"
        )
    if raw.status == 202 and route.gate is GateClass.UNGATED_WRITE:
        return Resource(app, raw.status, raw.json)
    return AppError(app, raw.status, normalise_code(app, code), message, raw.text)
