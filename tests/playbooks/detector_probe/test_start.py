"""``miassist_detector_start`` (FPRD FR-003.8, FR-003.16; FTASKS 2.3; A22)."""

from __future__ import annotations

from tests.playbooks.detector_probe.fakes import KEY, World, other_entries
from tests.playbooks.detector_probe.journey import journey

DESC = "refund requests in support messages"


def posts(j, path: str = "/api/v1/probe-monitors/behaviours") -> list:  # type: ignore[no-untyped-def]
    return [r for r in j.fakes["miworkbench"].requests if r.method == "POST" and r.path == path]


def test_proposal_then_one_post_then_none() -> None:
    with journey() as j:
        first = j.data("miassist_detector_start", {"description": DESC})
        assert first["data"]["recorded"] is False and posts(j) == []
        proposal = first["data"]["proposal"]
        assert (
            proposal["key"] == "refund-requests-in-support"
            and proposal["target_false_alarm_rate"] == 0.01
        )
        nxt = first["next_steps"][0]
        assert nxt["tool"] == "miassist_detector_start"
        assert {"key", "positive_meaning", "target_false_alarm_rate", "confirm"} <= set(nxt["args"])
        second = j.data("miassist_detector_start", nxt["args"])
        assert (
            second["data"]["key"] == proposal["key"]
            and second["data"]["catalogued_in"] == "miworkbench"
        )
        assert len(posts(j)) == 1
        body = posts(j)[0].body
        assert body["key"] == proposal["key"] and body["positive_meaning"] == DESC
        assert body["target_fpr"] == 0.01
        again = j.data("miassist_detector_start", nxt["args"])
        assert again["data"]["key"] == proposal["key"]
        assert len(posts(j)) == 1, "a repeat call makes no second POST"


def test_colliding_proposed_key_moves_to_dash_two() -> None:
    world = World()
    world.behaviours["refund-requests-in-support"] = {
        "key": "refund-requests-in-support",
        "positive_meaning": "SECRET-EXISTING-MEANING",
    }
    with journey(world=world) as j:
        first = j.data("miassist_detector_start", {"description": DESC})
        assert first["data"]["proposal"]["key"] == "refund-requests-in-support-2"
        assert "SECRET-EXISTING-MEANING" not in str(first)
        done = j.data("miassist_detector_start", first["next_steps"][0]["args"])
        assert done["data"]["key"] == "refund-requests-in-support-2"
        assert [r.body["key"] for r in posts(j)] == ["refund-requests-in-support-2"]
        assert "SECRET-EXISTING-MEANING" not in str(done)


def test_typed_existing_key_without_adoption_asks_and_posts_nothing() -> None:
    world = World()
    world.behaviours[KEY] = {"key": KEY, "positive_meaning": "SECRET-EXISTING-MEANING"}
    with journey(world=world) as j:
        asked = j.data(
            "miassist_detector_start", {"description": DESC, "key": KEY, "confirm": True}
        )
        assert asked["data"]["key_taken"] == KEY and asked["data"]["recorded"] is False
        assert posts(j) == [] and "SECRET-EXISTING-MEANING" not in str(asked)
        assert asked["next_steps"][0]["args"]["adopt_existing"] is True
        adopted = j.data("miassist_detector_start", asked["next_steps"][0]["args"])
        assert adopted["data"]["key"] == KEY and posts(j) == []


def test_other_entries_never_reach_a_result() -> None:
    world = World()
    other_entries(world)
    with journey(world=world) as j:
        first = j.data("miassist_detector_start", {"description": DESC})
        done = j.data("miassist_detector_start", first["next_steps"][0]["args"])
        status = j.data(
            "miassist_status", {"playbook": "detector-probe", "subject": done["data"]["key"]}
        )
        for result in (first, done, status):
            assert "other-" not in str(result)


def test_dataworks_only_records_in_miassist() -> None:
    with journey(("midataworks",)) as j:
        first = j.data("miassist_detector_start", {"description": DESC})
        done = j.data("miassist_detector_start", first["next_steps"][0]["args"])
        assert done["data"]["catalogued_in"] == "miassist"
        assert j.writes() == []


def test_beginner_and_expert_make_the_same_writes() -> None:
    logs = []
    for level in ("beginner", "expert"):
        with journey(level=level) as j:
            first = j.data("miassist_detector_start", {"description": DESC})
            done = j.data("miassist_detector_start", first["next_steps"][0]["args"])
            assert ("explain" in done) is (level == "beginner")
            logs.append(j.log())
    assert logs[0] == logs[1] and logs[0]


async def test_form_and_teaching_fallback_make_the_same_writes() -> None:
    """FR-003.16: the same call with and without form elicitation ends in the same app writes."""
    from mcp import Client
    from mcp.types import ElicitResult

    from tests.playbooks.detector_probe.fakes import fakes_for
    from tests.support.servers import make_server

    async def accept(context: object, params: object) -> ElicitResult:
        return ElicitResult(action="accept", content={"record_it": "yes"})

    bodies = []
    for with_form in (True, False):
        world = World()
        fakes = fakes_for(world)
        mcp, deps = make_server(("miworkbench", "miserver", "midataworks"), fakes)
        await deps.runtime.detector.probe_all()
        kwargs = {"mode": "2026-07-28", "elicitation_callback": accept} if with_form else {}
        async with Client(mcp, **kwargs) as client:
            first = await client.call_tool("miassist_detector_start", {"description": DESC})
            if not with_form:
                again = first.structured_content["next_steps"][0]["args"]
                await client.call_tool("miassist_detector_start", again)
        bodies.append([r.body for r in fakes["miworkbench"].requests if r.method == "POST"])
    assert bodies[0] == bodies[1] and len(bodies[0]) == 1
