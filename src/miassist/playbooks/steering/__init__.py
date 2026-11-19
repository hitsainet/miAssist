"""The steering playbook (miAssist 005): find a feature, try it, save it, serve it.

``register()`` adds its four tool specs to ``tools.EXTRA_SPECS`` and its status provider to
``playbooks.status.PROVIDERS`` (FR-005.3).
"""

from __future__ import annotations

from miassist.server.specs import ToolSpec

PLAYBOOK_ID = "steering"


def register(extra_specs: list[ToolSpec]) -> None:
    from miassist.playbooks.status import PROVIDERS
    from miassist.playbooks.steering.status import PROVIDER
    from miassist.playbooks.steering.tools import SPECS

    for spec in SPECS:
        if all(s.name != spec.name for s in extra_specs):
            extra_specs.append(spec)
    PROVIDERS[PLAYBOOK_ID] = PROVIDER
