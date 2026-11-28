"""Route constants for the steering playbook (005 FTID §10; FPRD §7 and FR-005.22).

The FPRD is the authority for each entry. ``adapters.routes`` registers ``STEERING_ROUTES`` into
Core's registry, and ``gpu_routes(vectors)`` the two caller-executed miWorkbench GPU routes
(``steer_sweep``, ``steer_combined``) ONLY when miWorkbench 045's vendored per-route vectors list
them (A38, A43): until 045-A0 makes the steering rows caller-executed and 001-V vendors their
vectors, Core's guards would refuse them, so the playbook's try and combined check answer a calm
refusal instead (OVN-miassist-pb045-13).

Core's own registrations are reused, not repeated: miWorkbench's approval file, get and list, and
miServer's clusters, models and approvals. Never registered (A14, A17, A23, A39): activation,
deactivation and intensity routes, the cluster hub, ``/consume``, every decide route, and
miWorkbench's judge-run, spot-check, judge-prompt, enhanced-labelling and publish routes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Final

from miassist.adapters.base import ANY, GateClass, Route

READ = GateClass.READ
LOAD_POLICY: Final = MappingProxyType({"X-miLLM-Load-Policy": "refuse"})


def _r(
    id: str, app: str, method: str, path: str, gate: GateClass, purpose: str, **kw: Any
) -> Route:
    return Route(
        id=f"{app}.{id}", app=app, method=method, path=path, gate=gate, purpose=purpose, **kw
    )


W, S = "miworkbench", "miserver"

EXTRACTIONS = _r("list_extractions", W, "GET", "/api/v1/extractions", READ, "steering: find")
EXTRACTION_FEATURES = _r(
    "extraction_features", W, "GET", "/api/v1/extractions/{extraction_id}/features", READ, "find"
)
FEATURE = _r("get_feature", W, "GET", "/api/v1/features/{feature_id}", READ, "steering: feature")
SAE = _r("get_sae", W, "GET", "/api/v1/saes/{sae_id}", READ, "steering: the feature's SAE")
STEERING_RESULT = _r(
    "steering_result", W, "GET", "/api/v1/steering/async/result/{task_id}", READ, "a sweep's result"
)
CLUSTER_PROFILES = _r(
    "save_profile",
    W,
    "POST",
    "/api/v1/cluster-profiles",
    GateClass.UNGATED_WRITE,
    "steering: save a profile (dial range [0, 1.0])",
    floor_entry="steering.save_profile",
)
CLUSTER_PROFILES_LIST = _r(
    "list_profiles", W, "GET", "/api/v1/cluster-profiles", READ, "save: adopt a profile by name"
)
CLUSTER_PROFILE_EXPORT = _r(
    "export_profile", W, "GET", "/api/v1/cluster-profiles/{profile_id}/export", READ, "serve"
)
CIRCUIT = _r("get_circuit", W, "GET", "/api/v1/circuits/{circuit_id}", READ, "serve: rung")
CIRCUIT_EXPORT = _r(
    "export_circuit", W, "GET", "/api/v1/circuits/{circuit_id}/export", READ, "serve: the document"
)
CLUSTERS_IMPORT = _r(
    "import_cluster",
    S,
    "POST",
    "/api/clusters/import",
    GateClass.UNGATED_WRITE,
    "serve: import a cluster, never active (A20)",
    floor_entry="steering.import_cluster",
    forbidden=MappingProxyType({"query.activate": ANY, "body.activate": ANY}),
)
CIRCUITS = _r("list_circuits", S, "GET", "/api/circuits", READ, "serve: circuits")
CIRCUITS_IMPORT = _r(
    "import_circuit",
    S,
    "POST",
    "/api/circuits/import",
    GateClass.UNGATED_WRITE,
    "serve: import a circuit, never active",
    floor_entry="steering.import_circuit",
    forbidden=MappingProxyType({"query.activate": ANY, "body.activate": ANY}),
)
MODEL_LOAD = _r(
    "load_model",
    S,
    "POST",
    "/api/models/{model_id}/load",
    GateClass.APP_GATED,
    "serve: load the cluster's model (model_load; the server runs it once approved)",
)
CHAT_COMPLETIONS = _r(
    "test_chat",
    S,
    "POST",
    "/v1/chat/completions",
    GateClass.UNGATED_WRITE,
    "serve: one bounded trial with inline steering, never loading a model",
    floor_entry="steering.test_chat",
    headers=LOAD_POLICY,
)
HEALTH_DETAILED = _r("health_detailed", S, "GET", "/api/health/detailed", READ, "serve: active")
CIRCUITS_ACTIVE = _r("active_circuit", S, "GET", "/api/circuits/active", READ, "serve: active")

STEERING_ROUTES: Final[tuple[Route, ...]] = (
    EXTRACTIONS,
    EXTRACTION_FEATURES,
    FEATURE,
    SAE,
    STEERING_RESULT,
    CLUSTER_PROFILES,
    CLUSTER_PROFILES_LIST,
    CLUSTER_PROFILE_EXPORT,
    CIRCUIT,
    CIRCUIT_EXPORT,
    CLUSTERS_IMPORT,
    CIRCUITS,
    CIRCUITS_IMPORT,
    MODEL_LOAD,
    CHAT_COMPLETIONS,
    HEALTH_DETAILED,
    CIRCUITS_ACTIVE,
)

#: The two caller-executed GPU routes (045 rows 31 and 32; A38), file-first through Core.
SWEEP_ID: Final = "miworkbench.steer_sweep"
COMBINED_ID: Final = "miworkbench.steer_combined"
GPU_ROUTES: Final[tuple[Route, ...]] = (
    _r(
        "steer_sweep",
        W,
        "POST",
        "/api/v1/steering/async/sweep",
        GateClass.APP_GATED,
        "try: one feature at several strengths (GPU, file-first)",
        file_first=True,
        approval_action="steer_sweep",
    ),
    _r(
        "steer_combined",
        W,
        "POST",
        "/api/v1/steering/async/combined",
        GateClass.APP_GATED,
        "save: the combined check of 2-3 features (GPU, file-first)",
        file_first=True,
        approval_action="steer_combined",
    ),
)


def gpu_routes(vectors: Iterable[Mapping[str, Any]]) -> tuple[Route, ...]:
    """The GPU routes whose (method, route, action) 045's vendored vectors carry; none otherwise."""
    listed = {(v.get("method"), v.get("route"), v.get("action")) for v in vectors}
    return tuple(r for r in GPU_ROUTES if (r.method, r.path, r.approval_action) in listed)


#: 045's vendored rows (method, route, action) for the steering GPU routes, as a LITERAL: empty until
#: 045-A0 makes the steering rows caller-executed and 001-V re-vendors its vectors. A test pins it
#: equal to the vendored file, so a re-vendor that adds rows 31 and 32 fails until this is updated,
#: and the routes register only then (OVN-miassist-pb045-13).
#: Integration (OVN-miassist-int-18), 2026-11-16: 001-V vendors 045-A0 @ fdb53989a (56 vectors), which
#: carries rows 31 and 32, and 045-A0's CALLER_TOOLS holds both actions; OR1-pb-2/3/5 are fixed. Both
#: routes stay app-gated and file-first: a call needs an operator-approved id.
ENABLED_GPU_ROWS: Final[tuple[dict[str, str], ...]] = (
    {"method": "POST", "route": "/api/v1/steering/async/sweep", "action": "steer_sweep"},
    {"method": "POST", "route": "/api/v1/steering/async/combined", "action": "steer_combined"},
)
