"""The steering playbook's status provider (005 FTDD §6; FPRD FR-005.20, FR-005.20a).

The subject is the saved profile's name (or, with miServer alone, the cluster's name). Status is
derived from the apps alone (never the progress record): a saved profile means the find, the try
and the save are done; miServer reporting the cluster active means the serve is done. Core's
``evaluate_done_when`` is called once per step that runs here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from miassist.adapters import steering as st
from miassist.errors import MiAssistError
from miassist.playbooks.done_when import evaluate_done_when
from miassist.playbooks.registry import ResolvedPlaybook
from miassist.playbooks.steering.actions import Down, get, items
from miassist.playbooks.steering.flow import Facts, derive

if TYPE_CHECKING:
    from miassist.server.specs import Deps


async def read(deps: Deps, subject: str) -> dict[str, Any]:
    installed = deps.runtime.installed
    facts: dict[str, Any] = {"profile": None, "served": None, "active": False}
    if not subject:
        return facts
    if "miworkbench" in installed:
        wb = deps.runtime.clients["miworkbench"]
        for item in items(
            await get(wb, st.CLUSTER_PROFILES_LIST, params={"limit": 100}), "profiles"
        ):
            if subject in (item.get("name"), item.get("id")):
                facts["profile"] = item
    if "miserver" in installed:
        sv = deps.runtime.clients["miserver"]
        for item in items(await get(sv, "miserver.list_clusters"), "clusters"):
            if subject in (item.get("name"), item.get("id")):
                facts["served"] = item
        # ClusterSummary.is_active, or detailed health's active_profile {id, name} (an OBJECT;
        # R1 review fix OR1-pb-4b, 2026-11-16).
        health = await get(sv, st.HEALTH_DETAILED)
        profile = health.get("active_profile") if isinstance(health, dict) else None
        named = isinstance(profile, dict) and subject in (profile.get("name"), profile.get("id"))
        served = facts["served"]
        facts["active"] = bool(named or (served is not None and served.get("is_active") is True))
    return facts


class SteeringStatusProvider:
    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        words = deps.guidance.playbooks["steering"].texts

        def w(key: str, **slots: Any) -> str:
            return deps.guidance.render(words[key], slots).text

        expected_override = None
        try:
            facts = await read(deps, subject)
        except (Down, MiAssistError):
            facts = {"profile": None, "served": None, "active": False}
            expected_override = w("status.unavailable")
        profile = facts["profile"]
        data = {
            "find": {"candidates": [{"profile": subject}]} if profile else {"candidates": []},
            "try": {"swept": bool(profile)},
            "save": {"profile_id": profile.get("id")} if profile else {},
            "serve": {"active": bool(facts["active"])},
        }
        done: list[str] = []
        first_open = None
        for step in playbook.runnable:
            if evaluate_done_when(step.done_when, data.get(step.id)):
                done.append(step.id)
            elif first_open is None:
                first_open = step
        state = derive(
            Facts(
                profile=bool(profile),
                imported=facts["served"] is not None,
                trial_done=facts["served"] is not None,
                active=bool(facts["active"]),
            )
        )
        waiting: list[dict[str, Any]] = []
        if state == "awaiting_activation":
            waiting.append(
                {"kind": "operator_action", "detail": w("handoff.cluster", name=subject, rung="-")}
            )
        nxt = None
        if first_open is not None and not waiting:
            key = {
                "miassist_steering_find": "concept",
                "miassist_steering_save": "name",
                "miassist_steering_serve": "cluster",
            }.get(first_open.tool, "feature")
            nxt = {
                "tool": first_open.tool,
                "args": {key: subject} if subject else {},
                "why": first_open.explain_expert,
            }
        return {
            "playbook_id": playbook.id,
            "playbook_version": playbook.version,
            "finished": first_open is None,
            "where": first_open.id if first_open else None,
            "done": done,
            "next": nxt,
            "waiting": waiting,
            "expected": expected_override or w(f"state.{state}", name=subject or "-"),
            "not_in_this_installation": playbook.not_in_this_installation,
        }


PROVIDER = SteeringStatusProvider()
