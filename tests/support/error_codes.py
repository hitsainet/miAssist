"""The sibling error codes miAssist's code branches on (ENH-013 006, FR-006.7, MA3; FTID §3.3).

A playbook or adapter that compares an app's ``code`` with a literal relies on the app sending
exactly that code. Each such literal is one row here, with the route, status and place in the
answer it is read from, the ``src/`` site that compares it, and the harness that confirms it in
the sibling's own interpreter (``tests/cross_repo/error_code_harnesses/``, IC-1; AT4).
``tests/contract/test_error_codes.py`` walks ``src/miassist``'s syntax trees and fails on a compared
literal that is in none of the three tables below.

Codes, as miAssist reads them (``results/app_answers.py``, ``_envelope``): miServer's and
miDataworks' ``error.code`` (miServer's ``/v1/`` routes as the OpenAI-compatible ``error.code``);
miWorkbench's ``detail.code`` (its gate's 422s) or ``detail.status`` (its 409 consume refusal,
which carries no code: PRE-006, MAP-2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


@dataclass(frozen=True)
class ReliedCode:
    app: str
    #: ``"<METHOD> <path>"`` of one registered route that answers it.
    route: str
    status: int
    #: Where the code is in the answer.
    where: Literal[
        "error.code", "error.details.code", "detail.code", "detail.status", "result.code"
    ]
    code: str
    #: The comparison in ``src/miassist/`` (``file:line`` at the commit that added the row).
    src: str
    #: The file under ``tests/cross_repo/error_code_harnesses/`` that prints the sibling's code.
    harness: str
    #: ``exact``: compared with ``==`` or ``in``; ``suffix``: ``answer.code.endswith(code)``
    #: (``answer.code`` is ``<app>.<code>``, lower-cased).
    match: Literal["exact", "suffix"] = "exact"


ERROR_CODES_RELIED_ON: Final = (
    ReliedCode(
        "miworkbench",
        "POST /api/v1/probe-monitors/runs",
        409,
        "detail.status",
        "consumed",
        "adapters/miworkbench.py:276",
        "miworkbench_consumed.py",
    ),
    ReliedCode(
        "miworkbench",
        "POST /api/v1/probe-monitors/runs",
        422,
        "detail.code",
        "mismatch",
        "adapters/miworkbench.py:282",
        "miworkbench_mismatch.py",
    ),
    ReliedCode(
        "miserver",
        "POST /api/probes/import",
        422,
        "error.details.code",
        "NAME_CONFLICT",
        "playbooks/detector_probe/actions.py:1357",
        "miserver_name_conflict.py",
    ),
    ReliedCode(
        "miserver",
        "POST /v1/chat/completions",
        409,
        "error.code",
        "model_not_resident",
        "playbooks/steering/actions.py:1053",
        "miserver_model_not_resident.py",
        "suffix",
    ),
    ReliedCode(
        "midataworks",
        "POST /api/v1/sources/hf",
        409,
        "error.code",
        "import_confirmation_required",
        "results/app_answers.py:93",
        "midataworks_import_confirmation_required.py",
    ),
    ReliedCode(
        "midataworks",
        "GET /api/v1/jobs/{job_id}",
        200,
        "result.code",
        "import_confirmation_required",
        "playbooks/dataset/actions.py:128",
        "midataworks_import_confirmation_required.py",
    ),
    ReliedCode(
        "midataworks",
        "POST /api/v1/sources/hf/search",
        504,
        "error.code",
        "search_timeout",
        "playbooks/dataset/actions.py:155",
        "midataworks_hub_timeouts.py",
    ),
    ReliedCode(
        "midataworks",
        "POST /api/v1/sources/hf/preview",
        504,
        "error.code",
        "preview_timeout",
        "playbooks/dataset/actions.py:182",
        "midataworks_hub_timeouts.py",
    ),
    ReliedCode(
        "midataworks",
        "POST /api/v1/detector-sets/send",
        409,
        "error.code",
        "send_refused",
        "playbooks/detector_probe/actions.py:1083",
        "midataworks_send_refused.py",
        "suffix",
    ),
)

#: Compared literals that are miAssist's own codes, not a sibling's, each with why.
OWN_CODES: Final = {
    "http_504": (
        "miAssist's own code for an app's 504 whose envelope names no code "
        '(results/app_answers.py, `code = f"http_{raw.status}"`); it joins the Hub timeouts in '
        "playbooks/dataset/actions.py's HF_TIMEOUTS"
    ),
}

#: Compared literals no sibling sends: each is a tracked defect, never a confirmed code.
DEAD_CODES: Final = {
    "token_missing": (
        "DEBT-006-1 (found 2026-11-25 by this table's AST walk): playbooks/dataset/actions.py:945 "
        "waits on a POST /api/v1/publishes refusal whose code ends `token_missing`. miDataworks "
        "(f730c52c, and the pin f6d6b98c) never answers one: a missing or read-only Hub token is "
        "check C-2 inside the publish job, which ends the publish `refused` with error.code "
        "`token_cannot_write` (services/publishing/publish_job.py:245-251). So the "
        "`wait.hub_credential` answer is never given. The operator's decision (2026-11-25): "
        "fixed in 006-2 (FTASKS 4.6a) by matching `token_cannot_write`; then this entry goes."
    ),
}
