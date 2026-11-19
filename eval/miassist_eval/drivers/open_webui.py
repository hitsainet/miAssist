"""The Open WebUI driver (FR-002.19, FR-002.24, FR-002.27; FTID §3.11).

ROUTES ARE UNVERIFIED until spike FTASKS 1.3 (by hand against a local container). Until then this
module holds the configuration it would send and refuses to start; it never runs under CI (M13).
"""

from __future__ import annotations

from typing import Any, ClassVar

from miassist_eval import budget, classes
from miassist_eval.classes import Refusal
from miassist_eval.drivers.base import ClientInfo, Driver

ELICITATION_TIMEOUT_S = 120
CONTAINER_PREFIX = "eval-"


def container_name(run_id: str) -> str:
    return f"{CONTAINER_PREFIX}{run_id}-owui"


class OpenWebUIDriver(Driver):
    name: ClassVar[str] = "open_webui"
    paid: ClassVar[bool] = True

    def preflight(self, cfg: dict[str, Any]) -> ClientInfo:
        if budget.in_ci():
            raise Refusal(classes.CI_REFUSED, "Open WebUI never runs in CI (M13)")
        raise Refusal(
            classes.CLIENT_NOT_STARTED,
            "the Open WebUI driver waits for spike FTASKS 1.3 (routes unverified)",
        )
