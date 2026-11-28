"""005 Feature Acceptance (9.1): the FRs the walk found without a test of their own.

ENH-012 acceptance (review/enh012-acceptance, 2026-11-26). Walking FR-005.1 to FR-005.22 against
the suite found four acceptance criteria no test checked:

- FR-005.21: identical side effects at both levels (request logs, ``data``, ``approval``,
  ``next_steps`` equal; ``explain`` only at beginner). 6.1's own note said "a separate both-levels
  run for 005 is not written".
- FR-005.20: status unchanged after deleting the progress record. The in-process session has no
  personal key, so no record was ever written and the test that read status never had one to
  delete.
- FR-005.12: identical app writes with and without the elicitation capability.
- FR-005.17 is in ``test_approval_facts.py`` (it found a defect, fixed with it).

A personal key is given to the in-process session by patching the one place each tool reads it
(``request_key``), so the tools resolve the level and record progress as they do behind
``/p/<key>/mcp``.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client
from mcp.types import ElicitResult

from tests.playbooks.steering.fake import Steering
from tests.playbooks.steering.support import KEY_HASH, Session, data
from tests.support.memory_store import MemoryStore

ONE = [{"feature": "evalfx-feat-1", "strength": 1.0}]
TWO = [{"feature": "evalfx-feat-1", "strength": 1.0}, {"feature": "evalfx-feat-2", "strength": 0.5}]


async def journey(store: MemoryStore) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]]]:
    """find -> try (files) -> approved -> try (one sweep) -> save -> serve (import, one trial)."""
    out: list[dict[str, Any]] = []
    async with Session(Steering(), store=store) as s:

        async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
            result = await s.call(tool, args)
            assert not result.is_error, result.content
            got = dict(result.structured_content)
            if tool == "miassist_status":  # it reports the level itself; the rest must agree
                got["data"] = {k: v for k, v in got["data"].items() if k != "level"}
            out.append(got)
            return got

        await call("miassist_steering_find", {"concept": "weather"})
        first = await call("miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi."})
        s.s.approve()
        await call(
            "miassist_steering_try",
            {"feature": "evalfx-feat-1", "prompt": "Hi.", "approval_id": first["approval"]["id"]},
        )
        saved = await call("miassist_steering_save", {"name": "sunny", "features": ONE})
        await call(
            "miassist_steering_serve", {"cluster": saved["data"]["profile_id"], "prompt": "Hello"}
        )
        await call("miassist_status", {"playbook": "steering", "subject": "sunny"})
        log = [
            (app, r.method, r.path, sorted(r.params.items()), r.body)
            for app in ("miworkbench", "miserver")
            for r in s.fakes[app].requests
        ]
    return log, out


async def test_both_levels_make_the_same_requests_and_answers(keyed: MemoryStore) -> None:
    """FR-005.21 (001 AC-7.1)."""
    beginner, expert = keyed, MemoryStore()
    beginner.levels[str(KEY_HASH)] = "beginner"
    expert.levels[str(KEY_HASH)] = "expert"
    log_b, out_b = await journey(beginner)
    log_e, out_e = await journey(expert)
    assert log_b == log_e, "the level changed a request"
    assert len(out_b) == len(out_e) == 6
    for b, e in zip(out_b, out_e, strict=True):
        assert b["guidance"] == "beginner" and e["guidance"] == "expert"
        for part in ("data", "approval", "next_steps"):
            assert b.get(part) == e.get(part), part
        assert b.get("explain") and not e.get("explain")


async def test_status_is_the_same_without_the_progress_record(keyed: MemoryStore) -> None:
    """FR-005.20: the status is derived from the apps; the progress record only remembers."""
    async with Session(Steering(), store=keyed) as s:
        saved = await s.call("miassist_steering_save", {"name": "sunny", "features": ONE})
        assert not saved.is_error
        assert keyed.progresses, "the save recorded no progress (the key did not reach the tool)"
        with_record = await s.call("miassist_status", {"playbook": "steering", "subject": "sunny"})
        keyed.progresses.clear()
        without = await s.call("miassist_status", {"playbook": "steering", "subject": "sunny"})
    got = with_record.structured_content["data"]["playbook"]
    assert got == without.structured_content["data"]["playbook"]
    assert got["done"] == ["find", "try", "save"] and got["where"] == "serve"


async def test_a_form_capable_client_makes_the_same_writes() -> None:
    """FR-005.12: steering asks no question by form (OVN-miassist-pb045-4: the choice is the next
    call), so a client that can show forms gets the same app writes and is never asked."""
    asked: list[Any] = []

    async def accept(context: object, params: object) -> ElicitResult:
        asked.append(params)
        return ElicitResult(action="accept", content={})

    writes = []
    for with_form in (True, False):
        async with Session(Steering()) as s:
            kwargs = {"mode": "2026-07-28", "elicitation_callback": accept} if with_form else {}
            async with Client(s.mcp, **kwargs) as client:
                first = await client.call_tool(
                    "miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi."}
                )
                s.s.approve()
                await client.call_tool(
                    "miassist_steering_try",
                    {
                        "feature": "evalfx-feat-1",
                        "prompt": "Hi.",
                        "approval_id": first.structured_content["approval"]["id"],
                    },
                )
                await client.call_tool("miassist_steering_save", {"name": "sunny", "features": ONE})
            writes.append(
                [
                    (r.path, r.body)
                    for app in ("miworkbench", "miserver")
                    for r in s.fakes[app].requests
                    if r.method == "POST"
                ]
            )
    assert writes[0] == writes[1] and len(writes[0]) == 3 and asked == []


async def test_the_filed_sweep_carries_the_features_layer_and_96_new_tokens() -> None:
    """FR-005.7's cassette criterion: ``layer`` from the SAE (the extraction's ``layer_index``,
    which is its SAE's layer), the feature's index and SAE, ``generation_params.max_new_tokens``
    96. Round 1 control E5-S07 (96 -> 256) survived the whole suite."""
    async with Session(Steering()) as s:
        await s.call("miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi."})
        (filed,) = s.log("miworkbench", "POST", "/api/v1/mcp/approvals")
    payload = filed.body["payload"]
    assert payload["generation_params"]["max_new_tokens"] == 96
    assert (payload["layer"], payload["feature_idx"], payload["sae_id"]) == (6, 42, "evalfx-sae-1")


async def test_a_combined_task_on_another_sae_is_not_this_clusters_check() -> None:
    """OR1-pb-16's SAE half (``CombinedSteeringResponse.sae_id``): the features match by index,
    layer and strength, but on another SAE those indexes are other features. Round 1 control
    E5-S12 (the SAE comparison removed) survived: only the features half had a test."""
    from tests.playbooks.steering.test_real_shapes import save_two

    s, done = await save_two(Steering(combined_sae_override="evalfx-sae-2"))
    assert done.is_error and done.content[0].text.startswith("combined_mismatch:")
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


async def test_a_combined_task_that_steered_more_features_is_not_this_clusters_check() -> None:
    """OR1-pb-16 says "exactly these members". Round 1 control E5-S13 (the comparison widened to
    "at least these") survived: the parametrised cases were all a different or a smaller set.
    A third feature changes the reply, so the check does not speak for the two saved. (Round 2:
    this test first named feature 2 by the wrong index, so it was a different set and the re-run of
    E5-S13 survived it; it now holds the two saved members plus one.)"""
    from tests.playbooks.steering.test_real_shapes import save_two

    applied = [  # the two saved (feature 1 is index 42, feature 2 index 7) and one more
        {"feature_idx": 42, "layer": 6, "strength": 1.0},
        {"feature_idx": 7, "layer": 6, "strength": 0.5},
        {"feature_idx": 99, "layer": 6, "strength": 2.0},
    ]
    s, done = await save_two(Steering(applied_override=applied))
    assert done.is_error and done.content[0].text.startswith("combined_mismatch:")
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


@pytest.mark.parametrize("strength,sign", [(-1.0, -1), (1.0, 1)], ids=["less", "more"])
async def test_a_saved_member_carries_the_sign_of_its_strength(strength: float, sign: int) -> None:
    """FR-005.8: the saved members' strengths are the usable strengths, and a ``less`` feature is
    saved turned down (miWorkbench ``ProfileMember``: ``strength`` with its ``sign``). Round 1
    control E5-S15 (every member saved with sign 1) survived: no save used a negative strength."""
    async with Session(Steering()) as s:
        result = await s.call(
            "miassist_steering_save",
            {"name": "gloomy", "features": [{"feature": "evalfx-feat-1", "strength": strength}]},
        )
        assert not result.is_error, result.content
        (post,) = s.log("miworkbench", "POST", "/api/v1/cluster-profiles")
    (member,) = post.body["members"]
    assert (member["strength"], member["sign"]) == (strength, sign)


async def test_the_trial_steers_at_the_clusters_dial() -> None:
    """FR-005.9: the one trial shows the cluster as it would serve, so each member's strength is
    scaled by the cluster's ``intensity`` (the 0-1 dial). Round 1 control E5-S18 (the scaling
    dropped) survived: every fake cluster had intensity 1.0, so the two always agreed."""
    st_ = Steering()
    doc = {
        "name": "sunny",
        "model": {"hf_id": "evalfx-org/evalfx-model"},
        "sae": {"mistudio_sae_id": "evalfx-sae-1"},
        "members": [{"feature_idx": 42, "strength": 2.0}],
    }
    st_.clusters.append(st_.cluster(doc, id="evalfx-cl-1", intensity=0.5))
    async with Session(st_, installed=("miserver",)) as s:
        result = await s.call("miassist_steering_serve", {"cluster": "sunny", "prompt": "Hi"})
        assert not result.is_error, result.content
        (chat,) = s.log("miserver", "POST", "/v1/chat/completions")
    assert chat.body["steering"]["features"] == [{"index": 42, "strength": 1.0}]


async def test_serve_a_circuit_imports_it_never_active_with_its_rung_and_no_trial() -> None:
    """FR-005.9's circuit half: export from miWorkbench, import into miServer with
    ``on_conflict=fail`` and no ``activate``, no trial (inline steering is feature-based), and the
    hand-off states the circuit's rung. ENH-012 acceptance: no test served a circuit."""
    async with Session(Steering()) as s:
        result = await s.call(
            "miassist_steering_serve", {"circuit": "evalfx-circ-1", "prompt": "Hi"}
        )
        got = data(result)
        (imported,) = s.log("miserver", "POST", "/api/circuits/import")
        assert imported.params == {"on_conflict": "fail"} and "activate" not in imported.body
        assert s.log("miserver", "POST", "/v1/chat/completions") == []
    assert got["state"] == "awaiting_activation" and got["rung"] == 2 and not got["active"]
    assert "rung 2" in got["waiting"][0]["detail"]


async def test_another_active_circuit_is_not_this_one() -> None:
    """Round 1 control E5-S19 (any active circuit read as this one) survived: no test served a
    circuit. With another circuit active, this one is imported, not active, and the hand-off
    names what activation would replace."""
    st_ = Steering()
    other = st_.sv_circuit("other-circuit", id="evalfx-svcirc-0")
    st_.sv_circuits.append(other)
    st_.active_circuits.append(other["id"])
    async with Session(st_) as s:
        result = await s.call("miassist_steering_serve", {"circuit": "evalfx-circ-1"})
    got = data(result)
    assert got["state"] == "awaiting_activation" and got["active"] is False
    assert got["replaces"] == "other-circuit"


async def test_this_circuit_active_reads_active() -> None:
    """The other side of E5-S19: once the operator activates THIS circuit in miServer, a repeat
    serve reads it as active from ``GET /api/circuits/active`` and hands nothing off. 006-1 review
    (F3): ``is_active = False`` survived, since no test served a circuit that was active."""
    st_ = Steering()
    async with Session(st_) as s:
        first = data(await s.call("miassist_steering_serve", {"circuit": "evalfx-circ-1"}))
        assert first["state"] == "awaiting_activation" and first["active"] is False
        (imported,) = st_.sv_circuits
        decoy = st_.sv_circuit("other-circuit", id="evalfx-svcirc-0")
        st_.sv_circuits.append(decoy)
        st_.active_circuits += [decoy["id"], imported["id"]]  # the operator activated it
        got = data(await s.call("miassist_steering_serve", {"circuit": "evalfx-circ-1"}))
    assert got["state"] == "active" and got["active"] is True
    assert got["miserver_circuit_id"] == imported["id"] and "replaces" not in got
    assert st_.sv_circuits == [imported, decoy], "the repeat's conflict adopts it by name"


async def test_without_miworkbench_a_circuit_is_served_by_its_miserver_name() -> None:
    """miServer alone: the circuit is found in ``GET /api/circuits`` (``CircuitListResponse``'s
    ``circuits``) by name, never imported. 006-1 review: no test reached this read, so its fake
    answered a bare list the contract does not allow."""
    st_ = Steering()
    mine = st_.sv_circuit("refusal-circuit", id="evalfx-svcirc-9")
    st_.sv_circuits.append(mine)
    async with Session(st_, installed=("miserver",)) as s:
        got = data(await s.call("miassist_steering_serve", {"circuit": "refusal-circuit"}))
        listed = s.log("miserver", "GET", "/api/circuits")
        imports = s.log("miserver", "POST", "/api/circuits/import")
    assert got["miserver_circuit_id"] == "evalfx-svcirc-9" and got["active"] is False
    assert len(listed) == 1 and imports == []


async def test_the_offered_call_again_spends_the_approval_it_was_filed_with() -> None:
    """FR-005.7, FR-005.15: a try with the person's own strengths files them; the call miAssist
    offers back (``approval.call_again_with``) must rebuild the same request, or miWorkbench
    refuses the spend (422 mismatch). Round 2 control E5-S27 (the offered args without the
    strengths, so the defaults come back) survived: every test re-called with its own args."""
    async with Session(Steering()) as s:
        first = await s.call(
            "miassist_steering_try",
            {"feature": "evalfx-feat-1", "prompt": "Hi.", "strengths": [0.3, 0.6]},
        )
        again = first.structured_content["approval"]["call_again_with"]
        s.s.approve()
        result = await s.call(again["tool"], again["args"])
        (filed,) = s.log("miworkbench", "POST", "/api/v1/mcp/approvals")
        sweeps = s.log("miworkbench", "POST", "/api/v1/steering/async/sweep")
    assert filed.body["payload"]["strength_values"] == [0.3, 0.6]
    assert data(result)["state"] == "swept" and len(sweeps) == 1


async def test_a_circuit_below_rung_two_is_handed_off_with_its_rung_and_the_warning() -> None:
    """FR-005.14: the circuit's rung is stated with its meaning; below rung 2 the hand-off adds
    the warning. Round 2 controls E2-H1 (the warning dropped) and E2-CI2 (the rung read as a
    constant 2) survived the rung-2 test alone."""
    from miassist.guidance.loader import Guidance

    warning = Guidance().playbooks["steering"].texts["handoff.below_rung2"]
    st_ = Steering(wb_circuits={"evalfx-circ-1": ("evalfx-circuit", 1)})
    async with Session(st_) as s:
        got = data(await s.call("miassist_steering_serve", {"circuit": "evalfx-circ-1"}))
    detail = got["waiting"][0]["detail"]
    assert got["rung"] == 1 and "rung 1" in detail and warning in detail
