"""Playbook status providers and their dispatch (001 FR-23, AC-23.3 - AC-23.6; BR-G-8; A25).

``miassist_status(playbook=...)`` looks the id up in ``PROVIDERS`` and calls that provider ONCE
with ``(deps, playbook, key_hash, subject)``; the document it returns is validated against
``$defs.playbook_status`` before it is shown. Core owns the tool, the dispatch and
``evaluate_done_when``; each playbook chain (003-005) registers its own provider here.

Core's own ``GenericStartHereProvider`` serves the four start-here playbooks and is STATELESS
(A25): for each step it runs the step tool's own handler in process with the step's ``args`` (no
MCP round trip; the same adapters and detector snapshot), evaluates ``done_when`` on that result's
``data``, and never touches the store, so the first call already shows real progress and leaves
no row behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from miassist.contracts.playbook import PlaybookStatus
from miassist.contracts.result_language import NextStep
from miassist.playbooks.done_when import evaluate_done_when
from miassist.playbooks.registry import ResolvedPlaybook

if TYPE_CHECKING:
    from miassist.server.specs import Deps


class StatusProvider(Protocol):
    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]: ...


def next_step(step: Any) -> dict[str, Any]:
    """A playbook step as the one suggested call (``playbook_status.next``)."""
    return {"tool": step.tool, "args": dict(step.args), "why": step.explain_expert}


class GenericStartHereProvider:
    """Live, read-only progress for a start-here playbook; keeps no state."""

    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        done: list[str] = []
        first_open = None
        for step in playbook.runnable:
            handler = deps.tool_functions[step.tool]
            result = await handler(None, **dict(step.args))
            structured = result.structured_content or {}
            data = None if result.is_error else structured.get("data")
            if evaluate_done_when(step.done_when, data):
                done.append(step.id)
            elif first_open is None:
                first_open = step
        forms = deps.guidance.playbook_forms
        if first_open is None:
            expected = forms.expected_finished
        else:
            expected = deps.guidance.render(
                forms.expected_next,
                {"step": first_open.title, "description": first_open.done_description},
            ).text
        return {
            "playbook_id": playbook.id,
            "playbook_version": playbook.version,
            "finished": first_open is None,
            "where": first_open.id if first_open else None,
            "done": done,
            "next": next_step(first_open) if first_open else None,
            "waiting": [],
            "expected": expected,
            "not_in_this_installation": playbook.not_in_this_installation,
        }


GENERIC = GenericStartHereProvider()


class PlaybookProvider:
    """A playbook chain's provider, imported on first use (the chains import Core's tools)."""

    def __init__(self, module: str) -> None:
        self.module = module

    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        import importlib

        provider: StatusProvider = importlib.import_module(self.module).PROVIDER
        return await provider(deps, playbook, key_hash, subject)


#: Status providers by playbook id. Core registers the start-here playbooks; 003-005 add theirs.
PROVIDERS: dict[str, StatusProvider] = {
    **{f"start-{app}": GENERIC for app in ("miworkbench", "miserver", "midataworks", "miforge")},
    "detector-probe": PlaybookProvider("miassist.playbooks.detector_probe.status"),
}


class StatusInvalid(ValueError):
    """A provider returned a document that is not a ``playbook_status``."""


def validated(document: Any) -> dict[str, Any]:
    """``document`` checked against ``$defs.playbook_status`` (its ``next`` against ``next_step``)."""
    try:
        PlaybookStatus.model_validate(document)
        if document.get("next") is not None:
            NextStep.model_validate(document["next"])
    except Exception as exc:
        raise StatusInvalid(str(exc).splitlines()[0]) from None
    return dict(document)
