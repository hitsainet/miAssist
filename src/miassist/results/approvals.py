"""Approval mapping (001 FR-16; FPRD §5.1.3, A18, A29, A30).

Two execution styles, two mappings:

- miWorkbench's caller-executed GPU routes (``file_first``): ``pending``/``approved``/``consumed``/
  ``failed``/``denied``/``expired`` become ``pending``/``approved``/``executed``/``failed``/
  ``rejected``/``expired``, ``then: call_again_with``.
- server-executed apps (miServer, miDataworks, miForge, and miWorkbench's relays, which pass the
  source app's approval through): the same word, never ``approved``, ``then: server_runs``.

An app status outside its style's vocabulary is refused (``approval_status_unknown``), never guessed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from miassist.errors import MiAssistError

Style = Literal["file_first", "server_executed", "relay"]

FILE_FIRST_STATUS: Final[Mapping[str, str]] = {
    "pending": "pending",
    "approved": "approved",
    "consumed": "executed",
    "failed": "failed",
    "denied": "rejected",
    "expired": "expired",
}
SERVER_STATUSES: Final = frozenset(
    {"pending", "executing", "executed", "failed", "rejected", "expired"}
)


def map_status(app: str, app_status: str, style: Style) -> tuple[str, str]:
    """``(contract status, then)`` for an app's approval status."""
    if style == "file_first":
        if app != "miworkbench" or app_status not in FILE_FIRST_STATUS:
            raise MiAssistError(
                "approval_status_unknown",
                f"{app} reported an approval status miAssist does not know",
            )
        return FILE_FIRST_STATUS[app_status], "call_again_with"
    if app_status not in SERVER_STATUSES:
        raise MiAssistError(
            "approval_status_unknown", f"{app} reported an approval status miAssist does not know"
        )
    return app_status, "server_runs"


def unwrap(body: Any) -> Mapping[str, Any]:
    """The approval object inside an app's answer (``approval``, ``data``, or the body itself)."""
    if isinstance(body, Mapping):
        for key in ("approval", "data"):
            inner = body.get(key)
            if isinstance(inner, Mapping) and ("id" in inner or "approval_id" in inner):
                return inner
        return body
    raise MiAssistError("approval_unreadable", "the app's approval answer was not an object")


def approval_object(
    app: str,
    body: Any,
    *,
    style: Style,
    summary: str,
    call_again_with: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A contract ``approval`` from an app's pending answer or status read."""
    inner = unwrap(body)
    approval_id = inner.get("approval_id", inner.get("id"))
    if not isinstance(approval_id, str | int) or str(approval_id) == "":
        raise MiAssistError("approval_unreadable", f"{app}'s approval answer carried no id")
    raw_status = str(inner.get("status", "pending"))
    if style == "file_first" and raw_status == "pending_approval":
        raw_status = "pending"
    status, then = map_status(app, raw_status, style)
    approval: dict[str, Any] = {
        "id": str(approval_id),
        "status": status,
        "decide_in": app,
        "then": then,
        "summary": summary[:500] or "-",
    }
    action = inner.get("action", inner.get("tool_name"))
    if isinstance(action, str) and action:
        approval["action"] = action
    if "expires_at" in inner:
        approval["expires_at"] = inner["expires_at"]
    reason = inner.get("reason", inner.get("decision_reason"))
    if (isinstance(reason, str) or reason is None) and status in ("rejected", "failed", "expired"):
        approval["reason"] = reason
    if then == "call_again_with" and call_again_with is not None:
        approval["call_again_with"] = dict(call_again_with)
    return approval
