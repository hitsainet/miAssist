"""The default recipe and the dataset name (004 FTDD §6 ``recipe.py``, T2; FTID I3; FPRD Q3, FR-004.11).

Pure functions. ``default_recipe`` builds Q3's two steps, ``dedup_exact`` then ``split``, with the
operator versions read from miDataworks at run time (T2): parameter names and forms are those of
the ``split`` 1.0.0 manifest, kept by 1.1.0 and 1.2.0 (``operators/native/curation/split.py``), and
are validated by miDataworks before anything is saved.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Final

RECIPE_FORMAT: Final = "dw.recipe/v1"
#: Split names that count as held out (a source with one keeps its own splits).
HELD_OUT_NAMES: Final = frozenset({"test", "validation", "valid", "eval", "dev", "holdout"})
#: miDataworks' ``DATASET_NAME_PATTERN`` (``models/dataset.py:18``).
DATASET_NAME_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
NAME_MAX: Final = 100


def has_held_out(splits: Sequence[str]) -> bool:
    return any(str(s).lower() in HELD_OUT_NAMES for s in splits)


def default_recipe(
    source_splits: Sequence[str],
    label_column: str | None,
    versions: Mapping[str, str],
) -> dict[str, Any]:
    """Q3's recipe body: drop exact duplicates, then split (keep the source's own splits when it
    has a held-out one; else 80/10/10 with validation and test held out, stratified by the label
    column when one is named)."""
    split_params: dict[str, Any]
    if has_held_out(source_splits):
        split_params = {"mode": "keep_source"}
    else:
        split_params = {
            "split_names": ["train", "validation", "test"],
            "split_fractions": [0.8, 0.1, 0.1],
            "held_out": ["validation", "test"],
        }
        if label_column:
            split_params["stratify_by"] = [label_column]
    return {
        "format": RECIPE_FORMAT,
        "steps": [
            {
                "operator": "dedup_exact",
                "version": versions["dedup_exact"],
                "params": {"collapse_whitespace": False},
            },
            {"operator": "split", "version": versions["split"], "params": split_params},
        ],
    }


def reason_keys(source_splits: Sequence[str], label_column: str | None) -> list[str]:
    """The guidance keys of the reasons for each default (FR-004.11), in order."""
    keys = [
        "reason.dedup",
        "reason.split_keep" if has_held_out(source_splits) else "reason.split_new",
    ]
    if label_column and not has_held_out(source_splits):
        keys.append("reason.stratify")
    keys.append("reason.name")
    return keys


def proposed_name(repo_or_name: str, taken: Collection[str]) -> str:
    """I3: the last path part, lower-cased and cut to miDataworks' pattern; ``-2``, ``-3`` on a
    clash."""
    last = repo_or_name.rstrip("/").rsplit("/", 1)[-1].lower()
    base = re.sub(r"[^a-z0-9-]+", "-", last).strip("-")
    base = re.sub(r"-+", "-", base) or "dataset"
    if not base[0].isalnum():
        base = "d" + base
    base = base[: NAME_MAX - 4].rstrip("-") or "dataset"
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}-{n}"
    if not DATASET_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"cannot make a dataset name from {repo_or_name!r}")
    return name


class PlanUnreadable(Exception):
    """The build plan's labelling facts could not be read: the build is the operator's."""


def plan_labels(plan: Any) -> int | None:
    """How many rows the build plan would label, or ``None`` when it labels nothing.

    miDataworks' ``services/build_plan_service.py:187-202`` (at 58087b1) nests the facts under
    ``labelling``: ``counted_steps`` lists the steps that call a model through an endpoint role
    (labelling), ``rows_counted`` the rows they would count, ``agent_needs_approval`` whether an
    agent would wait. Any counted step, counted row or wait stops the build (FR-004.7, A19).

    FAIL CLOSED (R1 review fix OR1-pb-1, 2026-11-16): a plan whose ``labelling`` facts are absent
    or not of those types raises ``PlanUnreadable``, and the caller hands the build to the
    operator; a labelling recipe never builds because a field moved."""
    labelling = plan.get("labelling") if isinstance(plan, Mapping) else None
    if not isinstance(labelling, Mapping):
        raise PlanUnreadable("the plan has no labelling facts")
    steps = labelling.get("counted_steps")
    rows = labelling.get("rows_counted")
    waits = labelling.get("agent_needs_approval")
    if (
        not isinstance(steps, list)
        or not isinstance(rows, int)
        or isinstance(rows, bool)
        or not isinstance(waits, bool)
    ):
        raise PlanUnreadable("labelling facts of other types")
    if steps or rows > 0 or waits:
        return rows
    return None
