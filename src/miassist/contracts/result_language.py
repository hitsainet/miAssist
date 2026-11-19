"""``mistudio.result-language/v1``: the suite's result language (001 FR-12; FPRD §5.1, CHAIN_PLAN A6
as amended 2026-11-15). The schema file ``docs/schemas/mistudio-result-language-v1.json`` is
GENERATED from these models by ``scripts/write_contracts.py``; never edit the file by hand.

Within v1 changes are additive only; a breaking change is v2 in a new file (PADR ADR-008).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from miassist.contracts._common import AppId, ErrorCode, ToolName, optional

CONTRACT = "mistudio.result-language/v1"
FILE_NAME = "mistudio-result-language-v1.json"
UNAVAILABLE_PATTERN = r"^[a-z][a-z0-9_-]{1,47}$"
MAX_NEXT_STEPS = 5


class ApprovalStatus(StrEnum):
    """Where an approval stands. miWorkbench's caller-executed routes map ``consumed`` to
    ``executed`` and ``denied`` to ``rejected``; the server-executed apps use these words as they
    are and never ``approved``."""

    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class CallAgain(BaseModel):
    """The call to make again once an approval is approved (caller-executed routes)."""

    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    args: dict[str, Any]


class Approval(BaseModel):
    """An action waiting for an app's operator. Only the operator decides it, in the app named by
    ``decide_in``; the caller cannot approve it."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=128)] = Field(
        description="The deciding app's own approval id."
    )
    status: ApprovalStatus
    decide_in: AppId
    then: Literal["server_runs", "call_again_with"] = Field(
        description="server_runs: the app runs the action itself once approved. call_again_with: "
        "the caller makes the call in call_again_with once approved."
    )
    summary: Annotated[str, Field(min_length=1, max_length=500)] = Field(
        description="Plain words: what will happen."
    )
    call_again_with: CallAgain | None = optional()
    action: str | None = optional(description="The app's own action name.")
    expires_at: datetime | None = None
    reason: str | None = Field(
        default=None, description="Why it was rejected, failed or expired, when known."
    )


class NextStep(BaseModel):
    """A suggested call: a tool on the server that emitted the result, with its arguments and the
    reason to make it."""

    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    args: dict[str, Any]
    why: Annotated[str, Field(min_length=1, max_length=300)]


class Unavailable(BaseModel):
    """A dependency that could not be reached, named, with the reason."""

    model_config = ConfigDict(extra="forbid")

    unavailable: str
    reason: str


class ErrorBody(BaseModel):
    """An error: a code, a one-line message, the fix, and the next steps (possibly none)."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    fix: str
    next_steps: list[NextStep]
    original: str | None = optional(description="The original error text, verbatim.")


class Explanation(BaseModel):
    """miAssist's plain-words explanation of a result, at the person's guidance level."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-emitted-by": "miassist"})

    what_happened: str
    why_it_matters: str
    what_good_looks_like: str
    next_step: str
    terms: list[str] = Field(description="Glossary keys of the terms the explanation uses.")


class Guidance(StrEnum):
    """The guidance level a result was rendered at."""

    BEGINNER = "beginner"
    EXPERT = "expert"


class AssistResult(BaseModel):
    """The structured result of every miAssist tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "x-emitted-by": "miassist",
            "dependentRequired": {"unavailable": ["reason"]},
        },
    )

    guidance: Guidance
    data: dict[str, Any] | list[Any] | None
    next_steps: list[NextStep]
    explain: Explanation | None = optional()
    approval: Approval | None = optional()
    unavailable: Annotated[str, Field(pattern=UNAVAILABLE_PATTERN)] | None = optional()
    reason: str | None = optional()


class ResultFields(BaseModel):
    """The fields any suite tool's result may carry beside its own. An app's own fields stay
    (``additionalProperties`` is true); an app's legacy ``next`` key is untouched and unconstrained:
    ``next_steps`` is the contract's key."""

    model_config = ConfigDict(
        extra="allow", json_schema_extra={"dependentRequired": {"unavailable": ["reason"]}}
    )

    approval: Approval | None = optional()
    next_steps: Annotated[list[NextStep], Field(max_length=MAX_NEXT_STEPS)] | None = optional()
    unavailable: Annotated[str, Field(pattern=UNAVAILABLE_PATTERN)] | None = optional()
    reason: str | None = optional()
    explain: Explanation | None = optional(description="Emitted by miAssist only.")


#: Every model, in ``$defs`` order, with the contract's name for it (FTDD §4.3).
DEFS: dict[str, type[Any]] = {
    "app_id": AppId,
    "approval_status": ApprovalStatus,
    "approval": Approval,
    "call_again": CallAgain,
    "next_step": NextStep,
    "tool_name": ToolName,
    "unavailable": Unavailable,
    "error_body": ErrorBody,
    "error_code": ErrorCode,
    "explanation": Explanation,
    "assist_result": AssistResult,
    "result_fields": ResultFields,
}
ROOT = "result_fields"
