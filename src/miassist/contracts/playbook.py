"""``mistudio.playbook/v1``: a playbook definition and its status (001 FR-13; FPRD §5.2). The schema
file ``docs/schemas/mistudio-playbook-v1.json`` is GENERATED from these models by
``scripts/write_contracts.py``; never edit the file by hand.

Every text field of a definition is a ``text_key`` into the playbook's guidance file
(``src/miassist/guidance/playbooks/<id>.yaml``; A8, A25): user-facing words are data, not code.
``playbook_status.next`` and ``waiting.approval`` reference the result-language file by relative
``$ref``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from miassist.contracts._common import AppId, ToolName, optional

CONTRACT = "mistudio.playbook/v1"
FILE_NAME = "mistudio-playbook-v1.json"
RESULT_LANGUAGE_FILE = "mistudio-result-language-v1.json"

#: Bounds on the RESOLVED text of each text key (checked by Core's registry after resolution).
TEXT_BOUNDS: dict[str, tuple[int, int]] = {
    "title": (1, 80),
    "goal": (1, 300),
    "step.title": (1, 80),
    "explain_beginner": (1, 1200),
    "explain_expert": (1, 300),
    "done_when.description": (1, 300),
}


def _ref(def_name: str, *, nullable: bool = False) -> Any:
    """Mark a field as a reference into the result-language file; the generator writes the
    relative ``$ref`` (Pydantic cannot resolve a cross-file reference itself)."""

    def apply(schema: dict[str, Any]) -> None:
        schema.clear()
        schema["x-external-ref"] = def_name
        if nullable:
            schema["x-nullable"] = True

    return apply


class TextKey(RootModel[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,119}$")]]):
    """A key into the playbook's guidance file. The resolved text has bounds: title 1-80, goal
    1-300, explain_beginner 1-1200, explain_expert 1-300, done_when.description 1-300."""


class WaitKind(StrEnum):
    """What a step can wait for. ``operator_action`` is a hand-off the operator does in the app,
    such as arming or activating."""

    APPROVAL = "approval"
    GPU = "gpu"
    JOB = "job"
    OPERATOR_ACTION = "operator_action"


class DoneWhen(BaseModel):
    """When a step is done: a JSON Pointer (RFC 6901) into the step tool's ``data`` and an operator.
    ``value`` is required when ``op`` is ``equals``, ``in`` or ``gte``, and absent otherwise."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "if": {"properties": {"op": {"enum": ["equals", "in", "gte"]}}, "required": ["op"]},
            "then": {"required": ["value"]},
            "else": {"not": {"required": ["value"]}},
        },
    )

    description: TextKey
    pointer: str = Field(description="An RFC 6901 JSON Pointer into the step tool's data.")
    op: Literal["exists", "truthy", "equals", "in", "gte"]
    value: Any = optional()


class Step(BaseModel):
    """One step of a playbook: the miAssist tool it calls and when it is done."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,47}$")]
    tool: ToolName = Field(description="A miAssist tool (miassist_...).")
    explain_beginner: TextKey
    explain_expert: TextKey
    done_when: DoneWhen
    title: TextKey | None = optional()
    entry: bool = Field(default=False, description="The journey may start here.")
    args: dict[str, Any] | None = optional(
        description="Literal arguments the status provider proposes in next."
    )
    waits_for: Annotated[list[WaitKind], Field(json_schema_extra={"uniqueItems": True})] | None = (
        optional()
    )
    requires_apps: (
        Annotated[list[AppId], Field(min_length=1, json_schema_extra={"uniqueItems": True})] | None
    ) = optional(
        description="Any of: the step is skipped, and listed in not_in_this_installation, when "
        "none is installed. Absent means the playbook's own list."
    )


class Playbook(BaseModel):
    """A playbook definition. Offered when at least one of ``requires_apps`` is installed and at
    least one ``entry`` step can run. Step ids are unique (checked by Core's registry)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["mistudio.playbook/v1"]
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,47}$")]
    version: Annotated[int, Field(ge=1)]
    title: TextKey
    goal: TextKey
    requires_apps: Annotated[
        list[AppId], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    steps: Annotated[
        list[Step],
        Field(
            min_length=1,
            json_schema_extra={
                "contains": {"properties": {"entry": {"const": True}}, "required": ["entry"]}
            },
        ),
    ]


class Waiting(BaseModel):
    """Something a playbook is waiting for. For ``operator_action``, ``detail`` says what to do and
    where."""

    model_config = ConfigDict(extra="forbid")

    kind: WaitKind
    detail: str
    approval: dict[str, Any] | None = Field(default=None, json_schema_extra=_ref("approval"))


class PlaybookStatus(BaseModel):
    """Where a person is in a playbook. ``next`` is one suggested step (or null), not a list."""

    model_config = ConfigDict(extra="forbid")

    playbook_id: str
    playbook_version: Annotated[int, Field(ge=1)]
    finished: bool
    where: str | None
    done: list[str]
    next: dict[str, Any] | None = Field(json_schema_extra=_ref("next_step", nullable=True))
    waiting: list[Waiting]
    expected: str = Field(description="Plain words: what to expect.")
    not_in_this_installation: list[str]


#: Every model, in ``$defs`` order, with the contract's name for it (FTDD §4.3).
DEFS: dict[str, type[Any]] = {
    "playbook": Playbook,
    "step": Step,
    "text_key": TextKey,
    "done_when": DoneWhen,
    "playbook_status": PlaybookStatus,
    "waiting": Waiting,
    "app_id": AppId,
    "tool_name": ToolName,
}
ROOT = "playbook"
