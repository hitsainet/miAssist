"""The tool specs: Core's and the extension point for playbook chains 003-005 (001 FTASKS 10.6)."""

from miassist.server.specs import ToolSpec
from miassist.tools.core import CORE_SPECS

#: Playbook chains (003-005) append their specs here; each is registered when its apps are
#: installed (``ToolSpec.offered``), like Core's.
EXTRA_SPECS: list[ToolSpec] = []


def all_specs() -> list[ToolSpec]:
    # Imported here, not at module level: the playbook tools import ``miassist.tools.core``.
    from miassist.playbooks.detector_probe.tools import DETECTOR_SPECS

    return [*CORE_SPECS, *EXTRA_SPECS, *DETECTOR_SPECS]


def _register_playbooks() -> None:
    """Each playbook chain's specs and status provider (004: the dataset playbook; 005: steering;
    003's are read lazily by ``all_specs`` and ``PROVIDERS``)."""
    from miassist.playbooks import dataset, steering

    dataset.register(EXTRA_SPECS)
    steering.register(EXTRA_SPECS)


_register_playbooks()
