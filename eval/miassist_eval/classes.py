"""Every refusal and failure class, defined once (TI-3; FTID §12).

The names are lowercase snake case and identical in code, records and reports.
``tests/unit/test_classes.py`` fails on any string literal in the package that looks like a class
name ending in a class suffix and is not defined here.
"""

from __future__ import annotations

from typing import Final

# Suite-start refusals (exit 2, zero runs).
LINT_REFUSED: Final = "lint_refused"
CASSETTE_INTEGRITY: Final = "cassette_integrity"
CASSETTE_STALE: Final = "cassette_stale"
REFERENCE_TOO_OLD: Final = "reference_too_old"
REFERENCE_MISSING: Final = "reference_missing"
FAIRNESS_PRECONDITION: Final = "fairness_precondition"
GPU_LIST_MISSING: Final = "gpu_list_missing"
FILTER_MODULE_MISSING: Final = "filter_module_missing"
CASSETTE_SCHEMA_MISSING: Final = "cassette_schema_missing"
BUDGET_EXCEEDED: Final = "budget_exceeded"
NOT_COMPARABLE: Final = "not_comparable"
CI_REFUSED: Final = "ci_refused"
DRIVER_NOT_REGISTERED: Final = "driver_not_registered"
#: R1 review fix (OR1-002-4), 2026-11-16: a GPU start the vendored vectors do not yet cover (steering
#: compare, sweep, combined). A suite or a recording of a goal that needs one refuses with it, and a
#: request to one fails the run with it, on the miAssist surface, until Core re-vendors.
GPU_LIST_INCOMPLETE: Final = "gpu_list_incomplete"

# Invalid run (infrastructure; re-attempted at most twice, FR-002.21).
CLIENT_NOT_STARTED: Final = "client_not_started"
SERVER_NOT_CONNECTED: Final = "server_not_connected"
PROVIDER_ERROR: Final = "provider_error"
COUNT_MISMATCH: Final = "count_mismatch"
HARNESS_ERROR: Final = "harness_error"

# Failed run (counted).
AGENT_ATTEMPTED_DECISION: Final = "agent_attempted_decision"
UNKNOWN_ROUTE: Final = "unknown_route"
MISSING_AGENT_HEADER: Final = "missing_agent_header"
OFF_RECORDING: Final = "off_recording"
CASSETTE_MISS: Final = "cassette_miss"
TURN_LIMIT: Final = "turn_limit"
TIME_LIMIT: Final = "time_limit"
WRONG_TOOL_LOOP: Final = "wrong_tool_loop"
ARGUMENT_REFUSAL: Final = "argument_refusal"
APPROVAL_MISREAD: Final = "approval_misread"
ASKED_AND_STOPPED: Final = "asked_and_stopped"
UNSUPPORTED_FIGURE: Final = "unsupported_figure"
MISSING_OUTCOME: Final = "missing_outcome"
STEP_ERROR: Final = "step_error"
RESULT_SHAPE: Final = "result_shape"
UNGATED_GPU_START: Final = "ungated_gpu_start"
FORBIDDEN_ROUTE: Final = "forbidden_route"
GPU_LIST_DRIFT: Final = "gpu_list_drift"
FIXTURE_NOT_ALLOWED: Final = "fixture_not_allowed"
UNFILTERED_LIST: Final = "unfiltered_list"
#: R1 review fix (OR1-002-2), 2026-11-16: an answer carrying a value that is not fixture data,
#: refused by the recorder and never recorded or passed on (OVN-miassist-eval-20, reversing OVN-7).
FOREIGN_ID: Final = "foreign_id"
#: R1 review fix (OR1-002-7), 2026-11-16: a non-JSON answer on a recording cannot be scanned.
TEXT_ANSWER_REFUSED: Final = "text_answer_refused"
#: R1 review fix (OR1-002-7), 2026-11-16: a secret-shaped or listed value in a take; never written.
SECRET_IN_TAKE: Final = "secret_in_take"

# Hand-off (counted as operator_handoffs, not a failure).
OPERATOR_HANDOFF: Final = "operator_handoff"

# Outcomes.
SUCCESS: Final = "success"
FAILED: Final = "failed"
INVALID: Final = "invalid"

SUITE_REFUSALS: Final = frozenset(
    {
        LINT_REFUSED,
        CASSETTE_INTEGRITY,
        CASSETTE_STALE,
        REFERENCE_TOO_OLD,
        REFERENCE_MISSING,
        FAIRNESS_PRECONDITION,
        GPU_LIST_MISSING,
        FILTER_MODULE_MISSING,
        CASSETTE_SCHEMA_MISSING,
        BUDGET_EXCEEDED,
        CI_REFUSED,
        DRIVER_NOT_REGISTERED,
        GPU_LIST_INCOMPLETE,
    }
)
INVALID_CAUSES: Final = frozenset(
    {CLIENT_NOT_STARTED, SERVER_NOT_CONNECTED, PROVIDER_ERROR, COUNT_MISMATCH, HARNESS_ERROR}
)
RUN_FAILURES: Final = frozenset(
    {
        AGENT_ATTEMPTED_DECISION,
        UNKNOWN_ROUTE,
        MISSING_AGENT_HEADER,
        OFF_RECORDING,
        TURN_LIMIT,
        TIME_LIMIT,
        WRONG_TOOL_LOOP,
        ARGUMENT_REFUSAL,
        APPROVAL_MISREAD,
        ASKED_AND_STOPPED,
        UNSUPPORTED_FIGURE,
        MISSING_OUTCOME,
        STEP_ERROR,
        RESULT_SHAPE,
        UNGATED_GPU_START,
        FORBIDDEN_ROUTE,
        GPU_LIST_DRIFT,
        FIXTURE_NOT_ALLOWED,
        UNFILTERED_LIST,
        GPU_LIST_INCOMPLETE,
        FOREIGN_ID,
        TEXT_ANSWER_REFUSED,
    }
)
ALL: Final = frozenset(
    {v for k, v in dict(globals()).items() if k.isupper() and isinstance(v, str)}
)


class Refusal(Exception):
    """A loud, named refusal (FTDD §5.5): ``cls`` is one of this module's classes."""

    def __init__(self, cls: str, detail: str = "") -> None:
        if cls not in ALL:
            raise ValueError(f"unknown class {cls!r}")
        super().__init__(f"{cls}: {detail}" if detail else cls)
        self.cls = cls
        self.detail = detail
