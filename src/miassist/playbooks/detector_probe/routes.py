"""The detector-probe playbook's routes (003 FPRD §7, FTID §10; FTASKS 1.4, 3.2, 4.2, 6.1, 7.2).

Registered into Core's registry by ``adapters/routes.py`` (``ROUTES = RouteRegistry(CORE_ROUTES +
DETECTOR_ROUTES)``), so every guard reads them from the live registry. Gate classes are FPRD §7's:
reads; the floor writes of FR-003.28, each with its ``floor_entry``. The ``file_first`` routes, the
download and the send register in their own pushes (R3M-7), never here first.

Never registered (A14, A17, A23, A39): miServer's arm, parity, single event and probe-hub routes;
every approve, deny, reject and ``/consume`` route; miDataworks' generation start; miWorkbench's
judge runs, spot-checks, judge-prompt tries, enhanced labelling and Hub publishes.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

from miassist.adapters.base import ANY, GateClass, Route

W, D, S = "miworkbench", "midataworks", "miserver"


def _read(id: str, app: str, path: str, purpose: str, **kw: Any) -> Route:
    return Route(
        id=id, app=app, method="GET", path=path, gate=GateClass.READ, purpose=purpose, **kw
    )


def _floor(id: str, app: str, path: str, entry: str, purpose: str, **kw: Any) -> Route:
    return Route(
        id=id,
        app=app,
        method="POST",
        path=path,
        gate=GateClass.UNGATED_WRITE,
        purpose=purpose,
        floor_entry=entry,
        **kw,
    )


PM = "/api/v1/probe-monitors"

# -- miWorkbench: reads ----------------------------------------------------------------------
BEHAVIOUR = _read("miworkbench.dp_behaviour", W, f"{PM}/behaviours/{{key}}", "the behaviour")
DATASET = _read("miworkbench.dp_dataset", W, "/api/v1/datasets/{dataset_id}", "a named dataset")
PROBE_VIEWS = _read("miworkbench.dp_probe_views", W, f"{PM}/datasets", "a named view (exact)")
#: R1 review fix (OR1-pb-7), 2026-11-16: one view by id. The behaviour detail lists a view without its
#: counts, distribution or archive time (``behaviour_catalogue.view_out``); this read has them.
PROBE_VIEW = _read(
    "miworkbench.dp_probe_view", W, f"{PM}/datasets/{{dataset_id}}", "a view of this journey"
)
RULE_RECOMMENDATION = _read(
    "miworkbench.dp_rule_recommendation",
    W,
    f"{PM}/datasets/{{dataset_id}}/rule-recommendation",
    "the pooling rules for the training view",
)
RUN_FORECAST = Route(
    id="miworkbench.dp_run_forecast",
    app=W,
    method="POST",
    path=f"{PM}/runs/forecast",
    gate=GateClass.READ,
    purpose="forecast: no row, no job (ADR-006, R2M-4)",
    computes_only=True,
)
RUN = _read("miworkbench.dp_run", W, f"{PM}/runs/{{run_id}}", "a run this journey started")
PROBE_REPORT = _read("miworkbench.dp_probe_report", W, f"{PM}/probes/{{probe_id}}", "the report")
PROBE_DEFINITION = _read(
    "miworkbench.dp_probe_definition", W, f"{PM}/probes/{{probe_id}}/definition", "the definition"
)
TASK_LOOKUP = _read(
    "miworkbench.dp_task_lookup", W, "/api/v1/task-queue/lookup/{task_id}", "a task's state"
)

# -- miWorkbench: floor writes (FR-003.28) ---------------------------------------------------
BEHAVIOURS_CREATE = _floor(
    "miworkbench.dp_behaviours_create",
    W,
    f"{PM}/behaviours",
    "detector.create_behaviour",
    "catalogue the behaviour",
)
PROBE_VIEWS_CREATE = _floor(
    "miworkbench.dp_probe_views_create",
    W,
    f"{PM}/datasets",
    "detector.register_views",
    "register a probe-dataset view",
)
NONSENSE_TEXT = _floor(
    "miworkbench.dp_nonsense_text",
    W,
    f"{PM}/nonsense-text",
    "detector.create_nonsense_text",
    "a nonsense-text set and its view (CPU only)",
)

# -- miWorkbench: the M16 download (push B, FTASKS 3.2) -----------------------------------
DATASET_DOWNLOAD = _floor(
    "miworkbench.dp_dataset_download",
    W,
    "/api/v1/datasets/download",
    "import.hf_miworkbench",
    "download a PUBLIC dataset (M16; after the check)",
    forbidden=MappingProxyType({"body.access_token": ANY}),
    touches_hub=True,
    hub_repo_param="body.repo_id",
    hub_repo_type="dataset",
)

# -- miWorkbench: GPU routes, file first (push B, FTASKS 4.2; A18, A32, R3M-2) ---------------
PROBE_RUNS = Route(
    id="miworkbench.dp_probe_runs",
    app=W,
    method="POST",
    path=f"{PM}/runs",
    gate=GateClass.APP_GATED,
    purpose="train a detector (GPU)",
    file_first=True,
    approval_action="start_probe_training_run",
)
PROBE_EVALUATE = Route(
    id="miworkbench.dp_probe_evaluate",
    app=W,
    method="POST",
    path=f"{PM}/probes/{{probe_id}}/evaluate",
    gate=GateClass.APP_GATED,
    purpose="evaluate a detector (GPU)",
    file_first=True,
    approval_action="evaluate_probe_monitor",
)

# -- push C (FTASKS 6.1, 7.2) ---------------------------------------------------------------
PROBE_DEFINITION_BUILD = Route(
    id="miworkbench.dp_probe_definition_build",
    app=W,
    method="POST",
    path=f"{PM}/probes/{{probe_id}}/definition",
    gate=GateClass.APP_GATED,
    purpose="build the definition (GPU; 045 A0)",
    file_first=True,
    approval_action="build_probe_definition",
)
DW_DETECTOR_SETS_SEND = Route(
    id="midataworks.dp_detector_sets_send",
    app=D,
    method="POST",
    path="/api/v1/detector-sets/send",
    gate=GateClass.APP_GATED,
    purpose="send the detector sets (hub_push; server runs it)",
)

# -- miDataworks: reads ----------------------------------------------------------------------
DW_BEHAVIOUR_STATUS = _read(
    "midataworks.dp_behaviour_status", D, "/api/v1/behaviours/{key}/status", "the journey"
)
DW_BEHAVIOUR_RESOLVE = _read(
    "midataworks.dp_behaviour_resolve", D, "/api/v1/behaviours/{key}/resolve", "the definition"
)
DW_DETECTOR_SEND = _read(
    "midataworks.dp_detector_send", D, "/api/v1/detector-sends/{send_id}", "a send's steps"
)
#: R3 review fix (OR3-int-2), 2026-11-16: a set's roles name the versions its send publishes.
DW_DETECTOR_SET = _read(
    "midataworks.dp_detector_set",
    D,
    "/api/v1/detector-sets/{set_id}",
    "the versions a send publishes (OR3-int-2)",
)

# -- miServer --------------------------------------------------------------------------------
SV_PROBES = _read("miserver.dp_probes", S, "/api/probes", "the imported probe (exact match)")
SV_PROBE_EVENTS = _read("miserver.dp_probe_events", S, "/api/probes/events", "event counts only")
SV_PROBES_IMPORT = _floor(
    "miserver.dp_probes_import",
    S,
    "/api/probes/import",
    "steering.import_probe",
    "import the definition (inert until armed)",
)

#: Push A (FTASKS 1.4): the reads and the four floor writes.
DETECTOR_ROUTES: Final[tuple[Route, ...]] = (
    BEHAVIOUR,
    DATASET,
    PROBE_VIEWS,
    PROBE_VIEW,
    RULE_RECOMMENDATION,
    RUN_FORECAST,
    RUN,
    PROBE_REPORT,
    PROBE_DEFINITION,
    TASK_LOOKUP,
    BEHAVIOURS_CREATE,
    PROBE_VIEWS_CREATE,
    NONSENSE_TEXT,
    DW_BEHAVIOUR_STATUS,
    DW_BEHAVIOUR_RESOLVE,
    DW_DETECTOR_SEND,
    SV_PROBE_EVENTS,
    SV_PROBES_IMPORT,
    # push B
    DATASET_DOWNLOAD,
    PROBE_RUNS,
    PROBE_EVALUATE,
    # push C
    PROBE_DEFINITION_BUILD,
    DW_DETECTOR_SETS_SEND,
    SV_PROBES,
    # R3 review fix (OR3-int-2)
    DW_DETECTOR_SET,
)
