"""The overhead budget on the changed path (001 FTASKS 12.4; FPRD §8): 200 ``miassist_overview``
calls through the real ASGI app over fake apps that answer at once, so the time measured is
miAssist's own: the transport, the guards, three app requests and the result builder.

The budget is p95 < 50 ms on a healthy machine. A bare wall-clock bound flakes on a shared runner
(suite memory ``check-ci-not-just-local-green``), so the bound is CALIBRATED in the same run: a
trivial call through the same stack (``miassist_status``, no app request) is timed interleaved with
the overview, and the budget scales with it when the machine is slow (50 ms per 5 ms of trivial
p95, never below 50 ms). The overview must also stay under ten trivial calls (measured ratio about
1.5), which no amount of contention moves.
"""

from __future__ import annotations

import logging
import time

from tests.support.app_factory import client
from tests.support.fake_apps import all_fakes
from tests.support.http_mcp import call_tool
from tests.support.scenarios import URLS, seed, wait_probed

CALLS = 200
BUDGET_MS = 50.0
TRIVIAL_REFERENCE_MS = 5.0
MAX_RATIO = 10.0


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(len(ordered) * 0.95) - 1]


def test_overview_p95_within_budget() -> None:
    logging.disable(logging.INFO)
    try:
        fakes = seed(all_fakes())
        with client(
            transports={a: f.transport() for a, f in fakes.items()}, apps="miforge", **URLS
        ) as test_client:
            wait_probed(test_client)
            for _ in range(10):  # warm up both paths
                call_tool(test_client, "/mcp", "miassist_overview", {"app": "miforge"})
                call_tool(test_client, "/mcp", "miassist_status")
            fakes["miforge"].requests.clear()
            overview: list[float] = []
            trivial: list[float] = []
            for _ in range(CALLS):
                start = time.perf_counter()
                result = call_tool(test_client, "/mcp", "miassist_overview", {"app": "miforge"})
                overview.append((time.perf_counter() - start) * 1000)
                assert result["isError"] is False
                start = time.perf_counter()
                call_tool(test_client, "/mcp", "miassist_status")
                trivial.append((time.perf_counter() - start) * 1000)
    finally:
        logging.disable(logging.NOTSET)
    # the path measured is the changed one: three app reads per overview call
    assert len(fakes["miforge"].calls("GET", "/api/v1/runs")) == CALLS
    budget = BUDGET_MS * max(1.0, p95(trivial) / TRIVIAL_REFERENCE_MS)
    measured = p95(overview)
    assert measured < budget, f"overview p95 {measured:.1f} ms, budget {budget:.1f} ms"
    assert measured / p95(trivial) < MAX_RATIO, (measured, p95(trivial))
