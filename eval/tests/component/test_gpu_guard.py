"""FR-002.11a, FR-002.11b: the GPU guard on each surface, through the live replay edge."""

from __future__ import annotations

from miassist_eval import classes, gpu_guard
from tests.support import harness

WB = {"X-MiStudio-Agent": "miassist"}
EVAL_PATH = "/api/v1/probe-monitors/probes/evalfx-p1/evaluate"
EVAL_TEMPLATE = "/api/v1/probe-monitors/probes/{probe_id}/evaluate"


def approved(
    edge,
    rid: str,
    tool: str = "evaluate_probe_monitor",
    by: str = "miassist",
    payload: dict | None = None,
) -> None:
    route = edge.resolve("miworkbench", "GET", f"/api/v1/mcp/approvals/{rid}")
    body = {
        "id": rid,
        "status": "approved",
        "tool_name": tool,
        "requested_by": by,
        "payload": (
            payload
            if payload is not None
            else {"_method": "POST", "_route": EVAL_TEMPLATE, "probe_id": "evalfx-p1"}
        ),
    }
    edge.observe(
        "miworkbench", route, "GET", f"/api/v1/mcp/approvals/{rid}", {}, WB, None, 200, {}, body
    )


def start(edge, rid: str | None = None, path: str = EVAL_PATH, body: object = None):
    headers = dict(WB)
    if rid:
        headers["X-MiStudio-Approval-Request"] = rid
    return edge.check("miworkbench", "POST", path, {}, headers, body)[1]


def test_no_id_is_refused() -> None:
    v = start(harness.edge())
    assert v is not None and v.cls == classes.UNGATED_GPU_START and v.status == 403


def test_an_id_read_only_pending_is_refused() -> None:
    edge = harness.edge()
    route = edge.resolve("miworkbench", "GET", "/api/v1/mcp/approvals/a1")
    edge.observe(
        "miworkbench",
        route,
        "GET",
        "/api/v1/mcp/approvals/a1",
        {},
        WB,
        None,
        200,
        {},
        {
            "id": "a1",
            "status": "pending",
            "tool_name": "evaluate_probe_monitor",
            "requested_by": "miassist",
        },
    )
    assert start(edge, "a1").cls == classes.UNGATED_GPU_START


def test_an_id_approved_for_another_action_is_refused() -> None:
    edge = harness.edge()
    approved(edge, "a1", tool="start_probe_training_run")
    assert start(edge, "a1").cls == classes.UNGATED_GPU_START


def test_an_id_approved_by_another_requester_is_refused() -> None:
    edge = harness.edge()
    approved(edge, "a1", by="mcp")
    assert start(edge, "a1").cls == classes.UNGATED_GPU_START


def test_an_id_approved_for_the_same_action_on_another_route_is_refused() -> None:
    """A38: start_labeling covers three routes; an approval for one does not start another."""
    edge = harness.edge()
    approved(
        edge,
        "a1",
        tool="start_labeling",
        payload={"_method": "POST", "_route": "/api/v1/labeling", "extraction_job_id": "x"},
    )
    assert (
        start(edge, "a1", path="/api/v1/labeling/panel", body={}).cls == classes.UNGATED_GPU_START
    )
    assert start(edge, "a1", path="/api/v1/labeling", body={}) is None


def test_an_id_approved_for_another_probe_is_refused() -> None:
    edge = harness.edge()
    approved(
        edge, "a1", payload={"_method": "POST", "_route": EVAL_TEMPLATE, "probe_id": "evalfx-p2"}
    )
    assert start(edge, "a1").cls == classes.UNGATED_GPU_START


def test_an_approved_id_passes_once_and_its_reuse_is_refused() -> None:
    edge = harness.edge()
    approved(edge, "a1")
    assert start(edge, "a1") is None
    assert start(edge, "a1").cls == classes.UNGATED_GPU_START


def test_the_id_may_come_from_an_object_body() -> None:
    edge = harness.edge()
    approved(edge, "a1")
    assert start(edge, None, body={"approval_request_id": "a1"}) is None


def test_a_bare_array_body_is_never_searched() -> None:
    edge = harness.edge()
    approved(edge, "a1")
    assert start(edge, None, body=["a1"]).cls == classes.UNGATED_GPU_START


def test_consume_is_forbidden_on_the_miassist_surface() -> None:
    edge = harness.edge()
    v = edge.check("miworkbench", "POST", "/api/v1/mcp/approvals/a1/consume", {}, WB, None)[1]
    assert v is not None and v.cls == classes.FORBIDDEN_ROUTE


def test_an_unlisted_route_answering_202_pending_is_gpu_list_drift() -> None:
    edge = harness.edge()
    path = "/api/v1/probe-monitors/datasets"
    route = edge.resolve("miworkbench", "POST", path)
    drift = edge.observe(
        "miworkbench", route, "POST", path, {}, WB, {}, 202, {"X-MiStudio-Approval": "pending"}, {}
    )
    assert drift == classes.GPU_LIST_DRIFT


def test_filing_and_status_reads_pass() -> None:
    edge = harness.edge()
    assert edge.check("miworkbench", "POST", "/api/v1/mcp/approvals", {}, WB, {})[1] is None
    assert edge.check("miworkbench", "GET", "/api/v1/mcp/approvals/a1", {}, WB, None)[1] is None


# --------------------------------------------------------------------- baseline surface
def consume(edge, tool: str) -> None:
    route = edge.resolve("miworkbench", "POST", "/api/v1/mcp/approvals/c1/consume")
    edge.observe(
        "miworkbench",
        route,
        "POST",
        "/api/v1/mcp/approvals/c1/consume",
        {},
        {},
        None,
        200,
        {},
        {"tool_name": tool, "status": "consumed"},
    )


def test_baseline_gated_start_without_consume_is_refused() -> None:
    edge = harness.edge("baseline")
    v = edge.check("miworkbench", "POST", EVAL_PATH, {}, {}, None)[1]
    assert v is not None and v.cls == classes.UNGATED_GPU_START


def test_baseline_one_consume_allows_one_start() -> None:
    edge = harness.edge("baseline")
    consume(edge, "evaluate_probe_monitor")
    assert edge.check("miworkbench", "POST", EVAL_PATH, {}, {}, None)[1] is None
    assert (
        edge.check("miworkbench", "POST", EVAL_PATH, {}, {}, None)[1].cls
        == classes.UNGATED_GPU_START
    )


def test_baseline_consume_is_not_forbidden() -> None:
    edge = harness.edge("baseline")
    assert (
        edge.check("miworkbench", "POST", "/api/v1/mcp/approvals/c1/consume", {}, {}, None)[1]
        is None
    )


DEFINITION = "/api/v1/probe-monitors/probes/evalfx-p1/definition"  # listed, not baseline-gated


def test_baseline_ungated_gpu_route_in_replay_passes_without_a_hold() -> None:
    edge = harness.edge("baseline")
    assert edge.check("miworkbench", "POST", DEFINITION, {}, {}, {})[1] is None


def test_baseline_hold_refuses_with_no_terminal(tmp_path) -> None:
    from miassist_eval import recorder

    edge = harness.edge("baseline", hold=recorder.tty_hold(str(tmp_path / "no-tty")))
    v = edge.check("miworkbench", "POST", DEFINITION, {}, {}, {})[1]
    assert v is not None and v.cls == classes.UNGATED_GPU_START


def test_baseline_hold_reads_y_from_the_terminal(tmp_path) -> None:
    from miassist_eval import recorder

    tty = tmp_path / "tty"
    tty.write_text("y\n")
    edge = harness.edge("baseline", hold=recorder.tty_hold(str(tty)))
    assert edge.check("miworkbench", "POST", DEFINITION, {}, {}, {})[1] is None


def test_baseline_hold_forwards_once_on_a_scripted_y() -> None:
    calls = []
    edge = harness.edge("baseline", hold=lambda start, req: calls.append(start.action) or True)
    assert edge.check("miworkbench", "POST", DEFINITION, {}, {}, {})[1] is None
    assert calls == ["build_probe_definition"]


def test_miassist_surface_never_prompts() -> None:
    prompts = []
    edge = harness.edge("miassist", hold=lambda s, r: prompts.append(s) or True)
    approved(edge, "a1")
    assert start(edge, "a1") is None
    assert prompts == []


def test_baseline_gated_set_is_the_five_probe_actions() -> None:
    assert gpu_guard.BASELINE_MCP_GATED == {
        "start_probe_training_run",
        "evaluate_probe_monitor",
        "start_probe_judge_run",
        "start_probe_spot_check",
        "recalibrate_probe_monitor",
    }


def test_an_approval_with_no_route_binds_nothing_and_is_refused() -> None:
    """R1 review fix (OR1-002-6), 2026-11-16: the reviewer's probe. An approved row whose payload
    carries no ``_route`` (a non-A38 approval) is refused, even for the matching action."""
    edge = harness.edge()
    approved(edge, "a9", payload={"probe_id": "evalfx-p2"})
    v = start(edge, "a9")
    assert v is not None and v.cls == classes.UNGATED_GPU_START
    assert "no route" in v.body["detail"]
    assert "a9" not in edge.state.used_ids, "a refused id must not be spent"
