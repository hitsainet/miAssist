"""The dataset playbook (miAssist 004): find, build, check and publish a dataset in miDataworks.

``register()`` wires the playbook into Core: its four tool specs into ``tools.EXTRA_SPECS`` and its
status provider into ``playbooks.status.PROVIDERS``. ``miassist.tools`` calls it once at import, so
the live registry (``tools/list``, ``prompts/list``, the status dispatch) carries the playbook in
every installation with miDataworks (FR-004.3, FR-004.4).
"""

from __future__ import annotations

from miassist.server.specs import ToolSpec

PLAYBOOK_ID = "dataset"


def register(extra_specs: list[ToolSpec]) -> None:
    from miassist.playbooks.dataset.status import PROVIDER
    from miassist.playbooks.dataset.tools import SPECS
    from miassist.playbooks.status import PROVIDERS

    for spec in SPECS:
        if all(s.name != spec.name for s in extra_specs):
            extra_specs.append(spec)
    PROVIDERS[PLAYBOOK_ID] = PROVIDER
