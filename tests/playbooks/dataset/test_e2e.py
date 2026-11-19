"""The dataset journey end to end through the real ASGI app's HTTP transport, at both levels
(004 FTASKS 6.1, 3.6; FPRD FR-004.10, FR-004.17, FR-004.20, §11 items 1 and 4).

find, build, check (with the operator's run), publish filed: at most 5 goal-tool calls; the
request logs at beginner and expert are equal; ``data``, ``approval`` and ``next_steps`` are equal;
``explain`` appears only at beginner; every request carries ``X-Dataworks-Agent: agent:miassist``;
exactly one gated write (the publish), no decision route, no preview before a passed check, no
``confirm_large``.
"""

from __future__ import annotations

import json
from typing import Any

from tests.playbooks.dataset.fake import PUBLIC, Dataworks, fakes_with
from tests.support.app_factory import client
from tests.support.http_mcp import call_tool
from tests.support.scenarios import URLS, wait_probed

KEY_B = "beginnerbeginnerbeginnerbe"
KEY_E = "expertexpertexpertexpertex"
REPO = "evalfx-org/published"


def run_of_all_green() -> dict[str, Any]:
    return {
        "id": "evalfx-run-1",
        "status": "completed",
        "results": [
            {"check": f"C-{n}", "outcome": "green", "reason": "ok", "next_step": "", "evidence": {}}
            for n in range(1, 10)
        ],
    }


def journey(level: str) -> tuple[list[dict[str, Any]], list[tuple[Any, ...]]]:
    dw_ = Dataworks(check_run=run_of_all_green())
    fakes = fakes_with(dw_)
    key = KEY_B if level == "beginner" else KEY_E
    path = f"/p/{key}/mcp"
    results = []
    with client(
        transports={a: f.transport() for a, f in fakes.items()}, apps="midataworks", **URLS
    ) as tc:
        wait_probed(tc)
        call_tool(tc, path, "miassist_set_guidance", {"level": level})
        fakes["midataworks"].requests.clear()
        found = call_tool(tc, path, "miassist_dataset_find", {"query": "support chats"})
        results.append(found)
        source = found["structuredContent"]["next_steps"][0]["args"]["source"]
        built = call_tool(tc, path, "miassist_dataset_build", {"source": source})
        results.append(built)
        name = built["structuredContent"]["data"]["dataset_name"]
        results.append(
            call_tool(
                tc,
                path,
                "miassist_dataset_check",
                {"dataset": name, "check_run_id": "evalfx-run-1"},
            )
        )
        results.append(
            call_tool(
                tc,
                path,
                "miassist_dataset_publish",
                {"dataset": name, "repo_id": REPO, "confirm": True},
            )
        )
    log = [
        (
            r.method,
            r.template,
            json.dumps(r.params, sort_keys=True),
            json.dumps(r.body, sort_keys=True),
            r.headers.get("x-dataworks-agent"),
        )
        for r in fakes["midataworks"].requests
        if r.template != "/api/health"
    ]
    return results, log


def test_journey_both_levels() -> None:
    beginner, log_b = journey("beginner")
    expert, log_e = journey("expert")
    assert len(beginner) <= 5  # FPRD Q10: at most 5 goal-tool calls to a filed publish
    assert log_b == log_e, "the level changed a request"
    for b, e in zip(beginner, expert, strict=True):
        assert not b["isError"] and not e["isError"]
        sb, se = b["structuredContent"], e["structuredContent"]
        assert "explain" in sb and "explain" not in se
        for field in ("data", "next_steps", "approval"):
            assert sb.get(field) == se.get(field), field
    states = [r["structuredContent"]["data"]["state"] for r in beginner]
    assert states == ["source_chosen", "version_ready", "checked", "publish_waiting"]
    # every request as agent:miassist; one gated write; no decision route; no confirm_large
    assert {agent for *_, agent in log_b} == {"agent:miassist"}
    gated = [row for row in log_b if row[0] == "POST" and row[1] == "/api/v1/publishes"]
    assert len(gated) == 1
    assert not [
        row
        for row in log_b
        if row[1] and row[1].endswith(("/approve", "/reject", "/approve-batch"))
    ]
    assert all("confirm_large" not in row[3] and "access_token" not in row[3] for row in log_b)
    templates = [row[1] for row in log_b]
    first_preview = templates.index("/api/v1/sources/hf/preview")
    exact_check = [
        i
        for i, row in enumerate(log_b)
        if row[1] == "/api/v1/sources/hf/search" and PUBLIC in row[3]
    ]
    assert exact_check and exact_check[0] < first_preview
