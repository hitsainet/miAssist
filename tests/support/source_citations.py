"""The sibling code and contract citations in ``src/miassist`` (2026-11-26; ENH-013 006 follow-up).

``src/`` comments cite sibling facts two ways: a code line (``path.py:N`` or ``path.py:N-M``), or a
pointer into a sibling's published answer contract (``docs/schemas/<app>-answers-v1.json#/...``).
``tests/contract/test_source_citations.py`` finds every one in the source text and requires each code
citation to be classified here by app; ``tests/cross_repo/test_miserver_citations_live.py`` then
proves every miServer citation still says what it claims at miAssist's miServer pin
(``tests/fixtures/openapi/miserver.json``'s ``commit``):
- a code citation's lines exist and hold its ``anchor`` text;
- a contract pointer resolves in miServer's contract.

A field the contract types is cited by its pointer, not a line (a line drifts; the contract is
re-vendored and pinned). A code fact the contract does not carry (a raise site, a payload rule, a
field the contract leaves open) keeps a line citation, and is held to its anchor.
"""

from __future__ import annotations

from typing import Final

#: Every code citation found in ``src/miassist`` (``(src file, cited path)``) and its app. Only
#: miServer's are resolved here; the other apps' are listed so a new citation is classified.
CITED: Final[dict[tuple[str, str], str]] = {
    ("adapters/dataset.py", "versions.py"): "midataworks",
    ("adapters/midataworks.py", "version_finalize.py"): "midataworks",
    ("adapters/midataworks.py", "lineage_service.py"): "midataworks",
    ("adapters/miworkbench.py", "api/v1/endpoints/mcp_approvals.py"): "miworkbench",
    ("playbooks/_shared/pending.py", "core/agent_origin.py"): "midataworks",
    ("playbooks/_shared/pending.py", "mcp_approvals.py"): "miworkbench",
    ("playbooks/_shared/pending.py", "approval_gate.py"): "miserver",
    ("playbooks/dataset/flow.py", "models/publish.py"): "midataworks",
    ("playbooks/dataset/flow.py", "models/job.py"): "midataworks",
    ("playbooks/dataset/flow.py", "core/cancellation.py"): "midataworks",
    ("playbooks/dataset/flow.py", "schemas/publishing.py"): "midataworks",
    ("playbooks/dataset/recipe.py", "models/dataset.py"): "midataworks",
    ("playbooks/dataset/recipe.py", "services/build_plan_service.py"): "midataworks",
    ("playbooks/dataset/status.py", "publishing.py"): "midataworks",
    ("playbooks/dataset/tools.py", "schemas/publishing.py"): "midataworks",
    ("playbooks/detector_probe/actions.py", "schemas/dataset.py"): "miworkbench",
    ("playbooks/detector_probe/actions.py", "schemas/model.py"): "miworkbench",
    ("playbooks/detector_probe/actions.py", "send_service.py"): "midataworks",
    ("playbooks/detector_probe/actions.py", "services/probe_service.py"): "miserver",
    ("playbooks/detector_probe/actions.py", "core/errors.py"): "miserver",
    ("playbooks/detector_probe/defaults.py", "schemas/probe_monitor.py"): "miworkbench",
    ("playbooks/detector_probe/defaults.py", "probe_monitors.py"): "miworkbench",
    ("playbooks/detector_probe/defaults.py", "services/eval_sample_size.py"): "miworkbench",
    ("playbooks/detector_probe/flow.py", "models/detector_send.py"): "midataworks",
    ("playbooks/steering/actions.py", "schemas/steering.py"): "miworkbench",
    ("playbooks/steering/actions.py", "cluster_hub_service.py"): "miserver",
    ("playbooks/steering/actions.py", "cluster_service.py"): "miserver",
    ("playbooks/steering/actions.py", "circuit_service.py"): "miserver",
    ("playbooks/steering/actions.py", "core/errors.py"): "miserver",
    ("playbooks/steering/actions.py", "approval_gate.py"): "miserver",
    ("playbooks/steering/actions.py", "schemas/openai.py"): "miserver",
    ("server/build.py", "miForge/backend/src/mcp_server/server.py"): "miforge",
}

#: Each miServer code citation (as written, ``path:lines``): its file in miServer's tree and text
#: that must appear in the cited lines at the pin.
MISERVER_LINES: Final[dict[str, tuple[str, str]]] = {
    "approval_gate.py:174-185": ("miserver/api/approval_gate.py", 'return ("agent:" + name)'),
    "approval_gate.py:461-473": (
        "miserver/api/approval_gate.py",
        "payload={n: jsonable_encoder(v)",
    ),
    "services/probe_service.py:286-300": (
        "miserver/services/probe_service.py",
        '"code": "NAME_CONFLICT"',
    ),
    "core/errors.py:666-670": ("miserver/core/errors.py", 'code = "VALIDATION_ERROR"'),
    "cluster_hub_service.py:307-308": (
        "miserver/services/cluster_hub_service.py",
        'hub_ref = {"repo_id": repo_id',
    ),
    "cluster_service.py:407-412": (
        "miserver/services/cluster_service.py",
        "A profile named '{name}' already exists",
    ),
    "circuit_service.py:1594-1598": (
        "miserver/services/circuit_service.py",
        "A circuit named '{name}' already exists",
    ),
    "cluster_service.py:102": ("miserver/services/cluster_service.py", "definition.model.hf_id"),
    "schemas/openai.py:223-231": (
        "miserver/api/schemas/openai.py",
        "`features: []` means EXPLICITLY UNSTEERED",
    ),
}
