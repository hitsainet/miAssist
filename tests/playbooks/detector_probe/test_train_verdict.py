"""File first, train, evaluate and judge (FPRD FR-003.10, FR-003.11, FR-003.13, FR-003.14,
FR-003.17, FR-003.19 - FR-003.22; FTASKS 2.6, 4.1 - 4.6, 5.1 - 5.4)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from miassist.adapters.miworkbench import canonical_payload
from tests.playbooks.detector_probe import fakes
from tests.playbooks.detector_probe.fakes import KEY, PM, World
from tests.playbooks.detector_probe.journey import journey
from tests.support.vectors import VECTORS_FILE

ROLES = [
    ("train", None, 1000),
    ("eval", "in_distribution", 1000),
    ("calibration", None, 700),
    ("everyday_text", None, 1200),
    ("nonsense_text", None, 2000),
]
VECTORS = {v["row"]: v for v in json.loads(VECTORS_FILE.read_text())["vectors"]}


def world_with_views(*, rows: int | None = None) -> World:
    world = World()
    world.behaviours[KEY] = {"key": KEY, "positive_meaning": "asks for money back"}
    for i, (role, dist, n) in enumerate(ROLES):
        world.views.append(
            {
                "id": f"evalfx-view-{i}",
                "role": role,
                "distribution": dist,
                "behaviour": KEY,
                "counts": {"positive": 100, "negative": (rows or n) - 100},
            }
        )
    world.models = [{"id": "evalfx-model", "status": "ready"}]
    return world


def gpu_calls(j: Any, suffix: str) -> list[Any]:
    return [
        r for r in j.fakes["miworkbench"].requests if r.method == "POST" and r.path.endswith(suffix)
    ]


def filings(j: Any) -> list[Any]:
    return [
        r
        for r in j.fakes["miworkbench"].requests
        if r.method == "POST" and r.path == "/api/v1/mcp/approvals"
    ]


def order(j: Any) -> list[str]:
    out = []
    for r in j.fakes["miworkbench"].requests:
        if r.path == "/api/v1/mcp/approvals" and r.method == "POST":
            out.append("file")
        elif r.path.startswith("/api/v1/mcp/approvals/") and r.method == "GET":
            out.append("status")
        elif (r.method == "POST" and r.path in (f"{PM}/runs",)) or r.path.endswith("/evaluate"):
            out.append("route")
        assert "/consume" not in r.path
    return out


def test_train_files_then_one_call_with_the_approved_id() -> None:
    world = world_with_views()
    with journey(world=world) as j:
        first = j.data("miassist_detector_train", {"key": KEY})
        approval = first["approval"]
        assert approval["decide_in"] == "miworkbench" and approval["then"] == "call_again_with"
        again = approval["call_again_with"]
        assert again["tool"] == "miassist_detector_train"
        assert again["args"]["key"] == KEY and again["args"]["approval_id"] == approval["id"]
        facts = first["data"]["approval_facts"]
        assert all(facts[k] for k in ("what", "cost", "where", "resume"))
        assert approval["id"] in facts["where"] and "25 minutes" in facts["cost"]
        assert gpu_calls(j, "/runs") == []
        waiting = j.data("miassist_detector_train", again["args"])
        assert waiting["approval"]["status"] == "pending" and gpu_calls(j, "/runs") == []
        world.approve(approval["id"])
        started = j.data("miassist_detector_train", again["args"])
        runs = gpu_calls(j, "/runs")
        assert len(runs) == 1 and len(filings(j)) == 1
        assert runs[0].headers["x-mistudio-approval-request"] == approval["id"]
        filed = filings(j)[0].body["payload"]
        assert filed == canonical_payload("POST", f"{PM}/runs", {}, {}, runs[0].body)
        assert started["data"]["state"] == "training" and started["data"]["run_id"]
        seen = order(j)
        assert seen[0] == "file" and seen[-1] == "route" and seen.count("route") == 1
        assert set(seen[1:-1]) == {"status"}, "only status reads between the filing and the call"
        body = runs[0].body
        assert body["config"] == {
            "rules": ["max"],
            "eval_max_rows": 20_000,
        }, "only keys that differ from the defaults, and the evaluation bound always (OR1-pb-7)"
        assert body["eval_dataset_ids"] == ["evalfx-view-1", "evalfx-view-3", "evalfx-view-4"]


def test_filing_has_the_shape_of_045s_vector_for_the_run_route() -> None:
    vector = VECTORS["23"]
    with journey(world=world_with_views()) as j:
        j.data("miassist_detector_train", {"key": KEY})
        filed = filings(j)[0].body
    assert filed["tool_name"] == vector["action"]
    assert (filed["payload"]["_method"], filed["payload"]["_route"]) == (
        vector["method"],
        vector["route"],
    )
    assert set(vector["payload"]) <= set(filed["payload"])


def test_repeat_first_call_without_memory_files_nothing_new() -> None:
    """FR-003.13 / 4.1: no personal link, so no progress; the list lookup finds the row."""
    with journey(world=world_with_views(), key=None) as j:
        first = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
        second = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
    assert len(filings(j)) == 1
    assert second["approval"]["id"] == first["approval"]["id"]


def test_digest_covers_the_whole_payload() -> None:
    """V-5: a row whose BODY matches but whose route differs is not this request."""
    world = world_with_views()
    with journey(world=world, key=None) as j:
        j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
        row = next(iter(world.approvals.values()))
        row["payload"] = {**row["payload"], "_route": "/api/v1/probe-monitors/other"}
        j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
    assert len(filings(j)) == 2


def test_rejected_is_shown_and_refiled_only_with_ask_again() -> None:
    world = world_with_views()
    with journey(world=world) as j:
        first = j.data("miassist_detector_train", {"key": KEY})
        world.deny(first["approval"]["id"], "the card is busy tonight")
        shown = j.data("miassist_detector_train", {"key": KEY})
        assert (
            shown["data"]["state"] == "rejected"
            and "the card is busy tonight" in shown["data"]["reason"]
        )
        assert shown["next_steps"][0]["args"]["ask_again"] is True
        assert len(filings(j)) == 1 and gpu_calls(j, "/runs") == []
        j.data("miassist_detector_train", {"key": KEY, "ask_again": True})
    assert len(filings(j)) == 2


def test_a_denied_request_without_memory_is_shown_not_refiled() -> None:
    """Integration (OVN-miassist-int-13), 2026-11-16: 003's gate calls the merged lookup with
    ``include_closed=True``. With no personal link (no progress), the list lookup finds the denied
    row of the same request and reports it; nothing is filed again without ``ask_again``."""
    world = world_with_views()
    with journey(world=world, key=None) as j:
        first = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
        world.deny(first["approval"]["id"], "the card is busy tonight")
        shown = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
    assert len(filings(j)) == 1 and gpu_calls(j, "/runs") == []
    assert shown["data"]["state"] == "rejected"


def test_failed_run_is_a_failed_step_with_its_reason() -> None:
    world = world_with_views()
    with journey(world=world) as j:
        first = j.data("miassist_detector_train", {"key": KEY})
        world.approve(first["approval"]["id"])
        started = j.data("miassist_detector_train", first["approval"]["call_again_with"]["args"])
        world.runs[started["data"]["run_id"]].update(
            status="failed", error_message="CUDA out of memory"
        )
        after = j.data("miassist_detector_train", {"key": KEY})
        status = j.data("miassist_status", {"playbook": "detector-probe", "subject": KEY})
    assert after["data"]["state"] == "failed" and "CUDA out of memory" in after["data"]["reason"]
    assert after["next_steps"], "one next step"
    assert world.approvals[first["approval"]["id"]]["status"] == "consumed"
    assert status["data"]["playbook"]["where"] == "train"


def test_route_refusing_after_consume_is_failed_and_not_refiled() -> None:
    world = world_with_views()
    with journey(world=world) as j:
        first = j.data("miassist_detector_train", {"key": KEY})
        world.approve(first["approval"]["id"])

        def refuse(r: Any) -> Any:
            # The real gate consumes first, then the handler refuses and the approval is marked
            # failed (core/approval_gate.py:323-330, A40): a 422 with the handler's own detail.
            world.approvals[first["approval"]["id"]].update(
                status="failed", reason="model files missing"
            )
            return fakes.wb(f"POST {PM}/runs", 422, {"detail": "model files missing"})

        j.fakes["miworkbench"].on("POST", f"{PM}/runs", refuse)
        doc = j.data("miassist_detector_train", first["approval"]["call_again_with"]["args"])
        again = j.data("miassist_detector_train", {"key": KEY})
    assert doc["approval"]["status"] == "failed" and doc["data"]["state"] == "failed"
    assert again["data"]["state"] == "failed" and len(filings(j)) == 1


def test_unknown_expert_config_key_files_nothing() -> None:
    with journey(world=world_with_views()) as j:
        result = j.call("miassist_detector_train", {"key": KEY, "expert_config": {"turbo": True}})
    text = result["content"][0]["text"]
    assert result["isError"] and text.startswith("unknown_arguments:") and "turbo" in text
    assert "stride" in text and filings(j) == []


def test_known_expert_config_key_is_sent() -> None:
    with journey(world=world_with_views()) as j:
        j.data("miassist_detector_train", {"key": KEY, "expert_config": {"stride": 2}})
    assert filings(j)[0].body["payload"]["config"] == {
        "rules": ["max"],
        "eval_max_rows": 20_000,
        "stride": 2,
    }


def test_large_views_cap_eval_rows() -> None:
    with journey(world=world_with_views(rows=30_000)) as j:
        j.data("miassist_detector_train", {"key": KEY})
    assert filings(j)[0].body["payload"]["config"]["eval_max_rows"] == 20_000


def test_two_models_are_asked() -> None:
    world = world_with_views()
    world.models.append({"id": "evalfx-model-2", "status": "ready"})
    with journey(("miworkbench",), world=world) as j:
        doc = j.data("miassist_detector_train", {"key": KEY})
    assert doc["data"]["models"] == ["evalfx-model", "evalfx-model-2"] and filings(j) == []


def test_pending_cap_reaches_the_person() -> None:
    """2.6: Core's cap at 1; one open miAssist request already; the filing is refused."""
    world = world_with_views()
    world.approvals["mcp_ap_other"] = {
        "id": "mcp_ap_other",
        "status": "pending",
        "requested_by": "miassist",
        "tool_name": "evaluate_probe_monitor",
        "payload": {},
    }
    with journey(world=world, max_pending_approvals=1) as j:
        result = j.call("miassist_detector_train", {"key": KEY})
    assert result["isError"] and result["content"][0]["text"].startswith("too_many_pending:")
    assert filings(j) == []


# -- the verdict ---------------------------------------------------------------------------


def report(rung: int, *, ood: bool = True) -> dict[str, Any]:
    evals = [
        {"dataset_id": f"evalfx-view-{i}", "metrics": {"scored": True, "ci": {"low": low}}}
        for i, low in ((1, 0.97), (3, 0.91), (4, 0.99))
    ]
    return {
        "probe": {"id": "evalfx-probe-1", "rung": rung},
        "rung_next_step": "app wording",
        "catch_rate": (
            {
                "sets": [
                    {
                        "name": "ood-support-tickets",
                        "positives": 200,
                        "caught": 182,
                        "needed": 100,
                        "counts": True,
                    }
                ]
            }
            if ood
            else None
        ),
        "everyday_text": {
            "sets": [
                {
                    "name": "evalfx-everyday",
                    "rows": 5000,
                    "false_alarms": 3,
                    "allowed": 100,
                    "counts": True,
                }
            ]
        },
        "nonsense_text": {
            "sets": [
                {
                    "name": "evalfx-nonsense",
                    "rows": 2000,
                    "false_alarms": 0,
                    "allowed": 40,
                    "counts": True,
                }
            ]
        },
        "evaluations": evals,
    }


def trained(world: World) -> World:
    world.runs["evalfx-run-1"] = {
        "id": "evalfx-run-1",
        "status": "completed",
        "selection": {"selected": "evalfx-probe-1"},
    }
    world.behaviours[KEY]["runs"] = [{"id": "evalfx-run-1", "status": "completed"}]
    world.reports["evalfx-probe-1"] = {
        "probe": {"id": "evalfx-probe-1", "rung": 0},
        "evaluations": [],
    }
    return world


def test_verdict_evaluates_every_view_with_a_bare_array() -> None:
    world = trained(world_with_views())
    with journey(world=world) as j:
        first = j.data("miassist_detector_verdict", {"key": KEY})
        assert gpu_calls(j, "/evaluate") == []
        filed = filings(j)[0].body
        assert filed["tool_name"] == "evaluate_probe_monitor"
        assert filed["payload"] == {
            "_method": "POST",
            "_route": f"{PM}/probes/{{probe_id}}/evaluate",
            "probe_id": "evalfx-probe-1",
            "dataset_ids": ["evalfx-view-1", "evalfx-view-3", "evalfx-view-4"],
            "sample_rows": 20_000,
        }
        assert set(filed["payload"]) == set(VECTORS["24"]["payload"]) | {"sample_rows"}
        world.approve(first["approval"]["id"])
        running = j.data("miassist_detector_verdict", first["approval"]["call_again_with"]["args"])
        call = gpu_calls(j, "/evaluate")
        assert len(call) == 1 and call[0].body == [
            "evalfx-view-1",
            "evalfx-view-3",
            "evalfx-view-4",
        ]
        assert (
            call[0].params == {"sample_rows": "20000"} and running["data"]["state"] == "evaluating"
        )
        world.reports["evalfx-probe-1"] = report(2)
        judged = j.data("miassist_detector_verdict", {"key": KEY})
    assert judged["data"]["rung"] == 2 and judged["data"]["state"] == "judged"
    explain = judged["explain"]["what_happened"]
    assert "rung 2" in explain and "91% of positives" in explain and "182 of 200" in explain
    assert "0.6 false alarms per 1,000" in explain and "allowed: up to 20.0" in explain
    assert "ready to serve" in explain
    assert judged["data"]["summary"].startswith("rung 2 · out-of-distribution catch 91% (182/200)")


def test_large_views_sample_on_evaluate() -> None:
    world = trained(world_with_views(rows=30_000))
    with journey(world=world) as j:
        first = j.data("miassist_detector_verdict", {"key": KEY})
        world.approve(first["approval"]["id"])
        j.data("miassist_detector_verdict", first["approval"]["call_again_with"]["args"])
        call = gpu_calls(j, "/evaluate")[0]
    assert call.params == {"sample_rows": "20000"}
    assert filings(j)[0].body["payload"]["sample_rows"] == 20000


def test_rung_one_verdict_names_the_missing_source() -> None:
    world = trained(world_with_views())
    world.reports["evalfx-probe-1"] = report(1, ood=False)
    with journey(world=world, store=None) as j:
        doc = j.data("miassist_detector_verdict", {"key": KEY})
    text = doc["explain"]["what_happened"]
    assert "rung 1" in text and "No set from a different source" in text
    assert "ready to serve" not in text and "ood_hf_repo" in text


def test_corpus_sized_views_never_spend_an_approval_on_a_refusal() -> None:
    """R1 review fix (OR1-pb-7), 2026-11-16. The behaviour detail carries no view sizes, and
    miWorkbench refuses an unbounded corpus-sized evaluation AFTER consuming the approval (A40). The
    playbook always sends the bound, so both GPU calls run and neither approval is spent on a 422.
    """
    world = world_with_views(rows=1_000_000)
    with journey(world=world) as j:
        first = j.data("miassist_detector_train", {"key": KEY})
        world.approve(first["approval"]["id"])
        started = j.data("miassist_detector_train", first["approval"]["call_again_with"]["args"])
        assert started["data"]["state"] == "training", started["data"]
        assert world.approvals[first["approval"]["id"]]["status"] == "consumed"
        world.runs[started["data"]["run_id"]].update(
            status="completed", selection={"selected": "evalfx-probe-1"}
        )
        world.reports["evalfx-probe-1"] = {"probe": {"id": "evalfx-probe-1", "rung": 0}}
        verdict = j.data("miassist_detector_verdict", {"key": KEY})
        world.approve(verdict["approval"]["id"])
        running = j.data(
            "miassist_detector_verdict", verdict["approval"]["call_again_with"]["args"]
        )
    assert running["data"]["state"] == "evaluating", running["data"]
    assert world.approvals[verdict["approval"]["id"]]["status"] == "consumed"
    assert len(gpu_calls(j, "/runs")) == 1 and len(gpu_calls(j, "/evaluate")) == 1


def test_the_verdict_finds_the_probe_the_run_selected() -> None:
    """R1 review fix (OR1-pb-6), 2026-11-16: ``ProbeRunResponse`` names the selected probe only in
    ``selection.selected``; the verdict reads its report from there without ``probe=``."""
    world = trained(world_with_views())
    world.reports["evalfx-probe-1"] = report(2)
    with journey(world=world) as j:
        judged = j.data("miassist_detector_verdict", {"key": KEY})
        reads = [r.path for r in j.fakes["miworkbench"].calls("GET", f"{PM}/probes/{{probe_id}}")]
    assert reads and set(reads) == {f"{PM}/probes/evalfx-probe-1"}
    assert judged["data"]["state"] == "judged" and judged["data"]["rung"] == 2


@pytest.mark.parametrize(
    "expert", [{"eval_max_rows": 50}, {"stride": 0}, {"target_fpr": 1.5}, {"rules": "max"}]
)
def test_a_request_the_app_would_refuse_files_no_approval(expert: dict[str, Any]) -> None:
    """R1 review fix (OR1-pb-7), 2026-11-16: the request is checked against miWorkbench's own
    request schema (``ProbeRunCreate``, vendored) before filing, so no approval is filed, approved
    and then spent on a 422."""
    with journey(world=world_with_views()) as j:
        result = j.call("miassist_detector_train", {"key": KEY, "expert_config": expert})
    text = result["content"][0]["text"]
    assert result["isError"] and text.startswith("invalid_arguments:"), text
    assert filings(j) == [] and gpu_calls(j, "/runs") == []


def test_an_out_of_distribution_view_is_evaluated_as_its_own_set() -> None:
    """R1 review fix (OR1-pb-7), 2026-11-16: the behaviour detail lists a view without its
    ``distribution``; read whole, an out-of-distribution view keeps its own role and is evaluated
    beside the in-distribution one (it is what rung 2's catch rate reads)."""
    world = trained(world_with_views())
    world.views.append(
        {
            "id": "evalfx-view-9",
            "role": "eval",
            "distribution": "out_of_distribution",
            "behaviour": KEY,
            "counts": {"positive": 50, "negative": 50},
        }
    )
    with journey(world=world) as j:
        j.data("miassist_detector_verdict", {"key": KEY})
        filed = filings(j)[0].body["payload"]
    assert {"evalfx-view-1", "evalfx-view-9"} <= set(filed["dataset_ids"])


def test_an_archived_view_is_not_part_of_the_journey() -> None:
    """R1 review fix (OR1-pb-7), 2026-11-16: an archived view (``archived`` in the detail,
    ``archived_at`` on the view) is never evaluated."""
    world = trained(world_with_views())
    world.views.append(
        {
            "id": "evalfx-view-8",
            "role": "eval",
            "distribution": "out_of_distribution",
            "behaviour": KEY,
            "counts": {"positive": 50, "negative": 50},
            "archived_at": "2026-11-01T00:00:00Z",
        }
    )
    with journey(world=world) as j:
        j.data("miassist_detector_verdict", {"key": KEY})
        filed = filings(j)[0].body["payload"]
    assert "evalfx-view-8" not in filed["dataset_ids"]
