"""miDataworks route constants for the dataset playbook (004 FTID §10; FPRD §7 and FR-004.21).

Integration (OVN-miassist-int-12), 2026-11-16: 004 wrote this module as ``adapters/midataworks.py``;
Core's credential screen (OVN-miassist-core-32) took that name first, so it lives here. ``SOURCE``
is Core's own ``midataworks.get_source`` registration (one route, one id), read lazily.

The FPRD is the authority for each entry's gate class, ``floor_entry``, ``gate_when``,
``touches_hub`` and ``forbidden``. ``adapters.routes`` registers ``DATASET_ROUTES`` into Core's
registry, so every guard (the write floor, the snapshot pins, the never-routes) sees them.

Core's own miDataworks registrations are reused, not repeated: ``midataworks.list_datasets``,
``midataworks.list_approvals``, ``midataworks.get_approval`` and the Hub search and preview
(reached only through ``hub.public_check``). Never registered (A14, A34): uploads, generation, label
runs, the token setting, ``POST /recipes/{id}/build``, ``POST /versions/{id}/publish-checks`` and
``POST /versions/{id}/leakage``.

Three POST routes are reads: the operator and recipe validations and the build plan write nothing
and are never gated (``versions.py:62-68``: "Writes nothing; never gated").
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final

from miassist.adapters.base import ANY, GateClass, Route

APP: Final = "midataworks"


def _route(id: str, method: str, path: str, gate: GateClass, purpose: str, **kw: Any) -> Route:
    return Route(
        id=f"midataworks.{id}",
        app=APP,
        method=method,
        path=path,
        gate=gate,
        purpose=purpose,
        **kw,
    )


READ = GateClass.READ

SOURCES = _route("list_sources", "GET", "/api/v1/sources", READ, "dataset: sources by name")
SOURCES_HF_IMPORT = _route(
    "hf_import",
    "POST",
    "/api/v1/sources/hf",
    GateClass.UNGATED_WRITE,
    "dataset: import a PUBLIC Hub dataset, after the exact-repository check (M16, A23)",
    floor_entry="import.hf_midataworks",
    gate_when=("field:body.access_token",),
    forbidden=MappingProxyType({"body.access_token": ANY, "body.confirm_large": ANY}),
    touches_hub=True,
    hub_repo_param="body.repo_id",
    hub_repo_type="dataset",
)
JOB = _route("get_job", "GET", "/api/v1/jobs/{job_id}", READ, "dataset: a job's state")
DATASETS_CREATE = _route(
    "create_dataset",
    "POST",
    "/api/v1/datasets",
    GateClass.UNGATED_WRITE,
    "dataset: create the dataset",
    floor_entry="dataset.create",
)
DATASET = _route("get_dataset", "GET", "/api/v1/datasets/{dataset_id}", READ, "dataset: one")
OPERATOR = _route("get_operator", "GET", "/api/v1/operators/{name}", READ, "recipe versions")
OPERATOR_VALIDATE = _route(
    "validate_operator",
    "POST",
    "/api/v1/operators/{name}/{version}/validate",
    READ,
    "dataset: validate one recipe step (writes nothing)",
    computes_only=True,
)
RECIPES_VALIDATE = _route(
    "validate_recipe",
    "POST",
    "/api/v1/recipes/validate",
    READ,
    "dataset: validate the whole recipe (writes nothing)",
    computes_only=True,
)
RECIPES = _route(
    "save_recipe",
    "POST",
    "/api/v1/recipes",
    GateClass.UNGATED_WRITE,
    "dataset: save the recipe",
    floor_entry="dataset.save_recipe",
)
RECIPES_LIST = _route(
    "list_recipes", "GET", "/api/v1/recipes", READ, "dataset: adopt a saved recipe by name (I3)"
)
RECIPE = _route("get_recipe", "GET", "/api/v1/recipes/{recipe_id}", READ, "dataset: a recipe")
VERSIONS_PLAN = _route(
    "plan_version",
    "POST",
    "/api/v1/versions/plan",
    READ,
    "dataset: dry-run the build (writes nothing, never gated)",
    computes_only=True,
)
VERSIONS = _route(
    "build_version",
    "POST",
    "/api/v1/versions",
    GateClass.UNGATED_WRITE,
    "dataset: build the version (conditional gate: agent labelling or lowered sensitivity, A19)",
    floor_entry="dataset.build_version",
    gate_when=("state:agent_label_plan_or_sensitivity_lowering",),
)
VERSION = _route("get_version", "GET", "/api/v1/versions/{version_id}", READ, "a version")
PUBLISH_BUILDS = _route(
    "build_files",
    "POST",
    "/api/v1/versions/{version_id}/publish-builds",
    GateClass.UNGATED_WRITE,
    "dataset: build the version's files",
    floor_entry="dataset.build_files",
)
PUBLISH_BUILD = _route(
    "get_publish_build", "GET", "/api/v1/publish-builds/{build_id}", READ, "the files build"
)
LEAKAGE_REPORT = _route(
    "get_leakage", "GET", "/api/v1/versions/{version_id}/leakage", READ, "an existing report"
)
SHORTCUT_AUDIT = _route(
    "get_shortcut_audit",
    "GET",
    "/api/v1/versions/{version_id}/shortcut-audit",
    READ,
    "the shortcut audit",
)
PUBLISH_CHECK_RUN = _route(
    "get_check_run",
    "GET",
    "/api/v1/publish-check-runs/{check_run_id}",
    READ,
    "a publish-check run the operator started (A34)",
)
PUBLISHES = _route(
    "publish",
    "POST",
    "/api/v1/publishes",
    GateClass.APP_GATED,
    "dataset: publish to the Hub (hub_push; the server runs it once approved)",
)
PUBLISHES_LIST = _route("list_publishes", "GET", "/api/v1/publishes", READ, "publishes")
PUBLISH = _route("get_publish", "GET", "/api/v1/publishes/{publish_id}", READ, "one publish")

#: Every route the dataset playbook registers, in FTID §10's order.
DATASET_ROUTES: Final[tuple[Route, ...]] = (
    SOURCES,
    SOURCES_HF_IMPORT,
    JOB,
    DATASETS_CREATE,
    DATASET,
    OPERATOR,
    OPERATOR_VALIDATE,
    RECIPES_VALIDATE,
    RECIPES,
    RECIPES_LIST,
    RECIPE,
    VERSIONS_PLAN,
    VERSIONS,
    VERSION,
    PUBLISH_BUILDS,
    PUBLISH_BUILD,
    LEAKAGE_REPORT,
    SHORTCUT_AUDIT,
    PUBLISH_CHECK_RUN,
    PUBLISHES,
    PUBLISHES_LIST,
    PUBLISH,
)

#: The POST routes that are reads (dry runs; they write nothing and are never gated).
POST_READS: Final = frozenset({OPERATOR_VALIDATE.id, RECIPES_VALIDATE.id, VERSIONS_PLAN.id})

#: Core's miDataworks registrations this playbook also calls (by id).
CORE_LIST_DATASETS: Final = "midataworks.list_datasets"
CORE_LIST_APPROVALS: Final = "midataworks.list_approvals"
CORE_GET_APPROVAL: Final = "midataworks.get_approval"


def __getattr__(name: str) -> Route:
    """``SOURCE``: Core's ``midataworks.get_source`` (registered once, by Core; the registry calls
    only its own object). Lazy, so this module and ``adapters.routes`` import in either order."""
    if name == "SOURCE":
        from miassist.adapters.routes import ROUTES

        return ROUTES.get("midataworks.get_source")
    raise AttributeError(name)
