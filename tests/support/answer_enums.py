"""The sibling answer enums ``src/`` hard-codes (ENH-013 006, FR-006.9, MA6; FTDD §6.4, FTID §3.4).

Each row names constants in ``src/miassist`` (dotted, ``NAME[key]`` for one value of a mapping, a
mapping alone for its keys) and the answer field whose values they are read against: the app, a
registered route, the status, and a pointer into the answer (``/`` between field names, ``[]``
for a list's items). Once the app is ``vendored`` the field's ``enum`` is read from its contract:
- ``partition``: the constants are disjoint and their union EQUALS the contract's ``enum``;
- ``subset``: every value is in the ``enum`` (with every row that names the same constants, so a
  set read against two apps' fields, ``OUTCOME``, is held to their union). The row says why it is
  not a partition.

A ``hand`` app's rows wait for its contract: 006-2 turns miDataworks' on, 006-3 miWorkbench's.
``tests/contract/test_answer_enums.py`` walks ``src/miassist/playbooks`` and ``adapters`` and fails
on a string-set constant a comparison reads that no row and no ``EXEMPT`` entry names.

Known before vendoring (FTDD §6.4, PRE-006's record): ``PUBLISHING`` holds ``running`` and
``COMPLETE`` holds ``complete``, ``done`` and ``succeeded``, which miDataworks never sends; both are
fixed in 006-2. ``SHOWABLE_TIERS``' ``anonymous`` is a guess of the same kind (its own comment says
so), and ``RUN_ACTIVE``, ``RUN_FAILED`` and the steering task sets carry values to check in 006-3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

P = "miassist.playbooks"
#: Each app's read of one approval, and where its status is.
APPROVAL_READS: Final = (
    ("miworkbench", "GET /api/v1/mcp/approvals/{request_id}", "/status"),
    ("midataworks", "GET /api/v1/approvals/{approval_id}", "/status"),
    ("miserver", "GET /api/approvals/{approval_id}", "/data/status"),
    ("miforge", "GET /api/v1/approvals/{approval_id}", "/status"),
)


@dataclass(frozen=True)
class AnswerEnum:
    app: str
    route: str
    status: int
    pointer: str
    constants: tuple[str, ...]
    mode: Literal["partition", "subset"]
    reason: str = ""


ANSWER_ENUMS: Final = (
    AnswerEnum(
        "midataworks",
        "GET /api/v1/publishes/{publish_id}",
        200,
        "/status",
        (
            f"{P}.dataset.flow.PUBLISHED",
            f"{P}.dataset.flow.PUBLISHING",
            f"{P}.dataset.flow.PUBLISH_FAILED",
        ),
        "partition",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/jobs/{job_id}",
        200,
        "/status",
        (
            f"{P}.dataset.flow.JOB_DONE",
            f"{P}.dataset.flow.JOB_FAILED",
            f"{P}.dataset.flow.JOB_RUNNING",
        ),
        "partition",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/publish-check-runs/{check_run_id}",
        200,
        "/status",
        (f"{P}.dataset.checks.COMPLETE",),
        "subset",
        "only the finished values: the other statuses are waited on",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/publish-check-runs/{check_run_id}",
        200,
        "/results/[]/outcome",
        (f"{P}.dataset.checks.OUTCOMES",),
        "partition",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/detector-sends/{send_id}",
        200,
        "/state",
        (f"{P}.detector_probe.flow.SEND_ENDED",),
        "subset",
        "only the states that end a send without its views",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/behaviours/{key}/status",
        200,
        "/next_step",
        (f"{P}.detector_probe.flow.AUTHORING_STEPS",),
        "subset",
        "only the journey steps the operator authors in miDataworks",
    ),
    AnswerEnum(
        "midataworks",
        "GET /api/v1/sources/{source_id}",
        200,
        "/token_tier",
        ("miassist.adapters.midataworks.SHOWABLE_TIERS",),
        "subset",
        "only the tiers of a source imported with no credential",
    ),
    AnswerEnum(
        "miworkbench",
        "GET /api/v1/probe-monitors/runs/{run_id}",
        200,
        "/status",
        (f"{P}.detector_probe.flow.RUN_ACTIVE", f"{P}.detector_probe.flow.RUN_FAILED"),
        "subset",
        "`completed` is compared on its own (flow.py:188)",
    ),
    AnswerEnum(
        "miworkbench",
        "GET /api/v1/steering/async/result/{task_id}",
        200,
        "/status",
        (
            f"{P}.steering.flow.TASK_RUNNING",
            f"{P}.steering.flow.TASK_FAILED",
            f"{P}.steering.actions.TASK_DONE",
        ),
        "subset",
        "Celery's task states as miWorkbench relays them; whether its contract enumerates them is "
        "read at 006-3",
    ),
    *(
        AnswerEnum(
            app,
            route,
            200,
            pointer,
            (f"{P}.detector_probe.flow.OUTCOME", f"{P}.detector_probe.actions.OUTCOME_STATE"),
            "subset",
            "the approval statuses read as a journey outcome, across both apps' approvals",
        )
        for app, route, pointer in APPROVAL_READS[:2]
    ),
    *(
        AnswerEnum(
            app,
            route,
            200,
            pointer,
            (
                f"{P}._shared.pending.OPEN_STATUSES[{app}]",
                f"{P}._shared.pending.CLOSED_STATUSES[{app}]",
            ),
            "subset",
            "the statuses miAssist searches an app's approval list by: each must be one the app "
            "sends, or the search finds nothing",
        )
        for app, route, pointer in APPROVAL_READS
    ),
    *(
        AnswerEnum(
            app,
            route,
            200,
            pointer,
            (f"{P}._shared.pending.OPEN", f"{P}._shared.pending.CLOSED"),
            "subset",
            "a remembered approval's status read as open or closed, across the four apps",
        )
        for app, route, pointer in APPROVAL_READS
    ),
)

#: String-set constants a comparison in ``playbooks/`` or ``adapters/`` reads that are not a
#: sibling's answer enum, each with why.
EXEMPT: Final = {
    "mcp_types.version.MODERN_PROTOCOL_VERSIONS": (
        "MCP protocol versions a client reports (the SDK's), not an app answer"
    ),
    f"{P}.dataset.actions.HF_TIMEOUTS": "error codes: tests/support/error_codes.py",
    f"{P}.dataset.actions.LICENCE_FILTERS": "request side: the licence filter miAssist sends",
    f"{P}.dataset.recipe.HELD_OUT_NAMES": "request side: split names in a recipe miAssist writes",
    f"{P}.dataset.flow.STATES": "miAssist's own playbook states",
    f"{P}.dataset.tools.WHY": "miAssist's own tool names",
    f"{P}.detector_probe.flow.KIND_STEP": "miAssist's own approval kinds and steps",
    f"{P}.detector_probe.flow.TOOL_OF": "miAssist's own tool names",
    f"{P}.detector_probe.status.APPROVAL": "miAssist's own step states",
    f"{P}.detector_probe.status.GPU": "miAssist's own step states",
    f"{P}.detector_probe.status.JOB": "miAssist's own step states",
    f"{P}.detector_probe.status.OPERATOR": "miAssist's own step states",
    "miassist.contracts.playbook.TEXT_BOUNDS": "miAssist's own playbook-definition fields",
    f"{P}.steering.flow.STATES": "miAssist's own playbook states",
    f"{P}._shared.pending.REQUESTED_BY": "the requester value miAssist sends, per app",
    f"{P}._shared.pending.ROUTES": "miAssist's own route table, per app",
    "miassist.adapters.base.ACKNOWLEDGE_KEYS": "request side: argument names miAssist refuses",
    "miassist.adapters.base.HEADERS": "the agent header miAssist sends, per app",
    "miassist.adapters.limits.REQUESTED_BY": "the requester value miAssist sends, per app",
    "miassist.adapters.limits._PAGING": "miAssist's own paging table, per app",
    "miassist.adapters.routes.UNGATED_WRITES_ALLOWED": "miAssist's own route ids",
}
