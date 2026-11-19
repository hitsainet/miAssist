"""Defaults with reasons: the view bodies and the run body (003 FPRD FR-003.14, FTDD §6,
FTID §3.3; I1, I2). Pure: no I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from miassist.errors import MiAssistError

#: miWorkbench's unsampled evaluation bound (``schemas/probe_monitor.py:61``).
MAX_UNSAMPLED_ROWS = 20_000
DEFAULT_TARGET_FPR = 0.01


@dataclass(frozen=True)
class DataChoice:
    """The person's own dataset, as the data tool's arguments name it."""

    dataset_id: str
    repo: str
    config: str | None
    split_train: str
    split_test: str
    split_calibration: str | None
    text_column: str
    label_column: str
    positive_values: tuple[str, ...]


def mapping(
    positives: Sequence[str], negatives: Sequence[str], *, calibration: bool
) -> dict[str, str]:
    """I2: the positives the person named, plus every value miWorkbench named and the person
    confirmed as negative. A calibration view never maps anything to positive (``:206-211``)."""
    out = dict.fromkeys(positives, "excluded" if calibration else "positive")
    out.update(dict.fromkeys(negatives, "negative"))
    return out


def view_bodies(
    choice: DataChoice, key: str, meaning: str, negatives: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """I1: three splits: the third (``split_calibration``) sets the bar; two: the test split's
    negatives set it (positives ``excluded``) and the verdict adds the caveat. Bodies by role."""
    base = {
        "dataset_id": choice.dataset_id,
        "input_column": choice.text_column,
        "label_column": choice.label_column,
        **({"config": choice.config} if choice.config else {}),
    }
    calibration_split = choice.split_calibration or choice.split_test
    return {
        "train": {
            **base,
            "name": f"{key} · train",
            "split": choice.split_train,
            "role": "train",
            "behaviour": key,
            "positive_meaning": meaning,
            "label_mapping": mapping(choice.positive_values, negatives, calibration=False),
        },
        "test": {
            **base,
            "name": f"{key} · test",
            "split": choice.split_test,
            "role": "eval",
            "distribution": "in_distribution",
            "behaviour": key,
            "positive_meaning": meaning,
            "label_mapping": mapping(choice.positive_values, negatives, calibration=False),
        },
        "calibration": {
            **base,
            "name": f"{key} · calibration",
            "split": calibration_split,
            "role": "calibration",
            "behaviour": key,
            "label_mapping": mapping(choice.positive_values, negatives, calibration=True),
        },
    }


def ood_body(
    choice: DataChoice, key: str, meaning: str, negatives: Sequence[str]
) -> dict[str, Any]:
    return {
        "dataset_id": choice.dataset_id,
        "input_column": choice.text_column,
        "label_column": choice.label_column,
        **({"config": choice.config} if choice.config else {}),
        "name": f"{key} · unseen ({choice.repo})"[:255],
        "split": choice.split_test,
        "role": "eval",
        "distribution": "out_of_distribution",
        "behaviour": key,
        "positive_meaning": meaning,
        "label_mapping": mapping(choice.positive_values, negatives, calibration=False),
    }


def everyday_body(
    dataset_id: str, key: str, config: str | None, split: str | None
) -> dict[str, Any]:
    """Everyday text: every row a negative (``"*"`` is allowed for text roles only, ``:187-191``);
    no behaviour, no meaning (miWorkbench refuses them on text roles, ``:192-205``)."""
    return {
        "dataset_id": dataset_id,
        "name": f"{key} · everyday text",
        "input_column": "text",
        "label_column": "text",
        "role": "everyday_text",
        "label_mapping": {"*": "negative"},
        **({"config": config} if config else {}),
        **({"split": split} if split else {}),
    }


def nonsense_body(key: str) -> dict[str, Any]:
    """A fresh nonsense-text set with miWorkbench's defaults (``probe_monitors.py:382-400``)."""
    return {"name": f"{key} · nonsense text", "rows": 2000, "seed": 0, "register_view": True}


def check_expert_config(config: Mapping[str, Any], accepted: frozenset[str]) -> None:
    """A37: an unknown key refuses ``unknown_arguments`` with the accepted names; nothing is filed."""
    unknown = sorted(set(config) - accepted)
    if unknown:
        raise MiAssistError(
            "unknown_arguments",
            f"expert_config does not take {', '.join(unknown)}; it takes {', '.join(sorted(accepted))}",
        )


def run_body(
    *,
    key: str,
    model_id: str,
    views: Mapping[str, Mapping[str, Any]],
    rules: Sequence[str],
    target_fpr: float | None,
    expert_config: Mapping[str, Any] | None,
    accepted: frozenset[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """The ``ProbeRunCreate`` body (FR-003.14) and the name of each default's reason. ``config``
    holds only the keys that differ from miWorkbench's defaults; ``expert_config`` is merged last.
    """
    config: dict[str, Any] = {}
    reasons = {
        "layers": "reason.layers",
        "gpu": "reason.gpu",
        "calibration_rows": "reason.calibration_rows",
    }
    if rules:
        config["rules"] = list(rules)
        reasons["rules"] = "reason.rules"
    fpr = target_fpr or DEFAULT_TARGET_FPR
    if fpr != DEFAULT_TARGET_FPR:
        config["target_fpr"] = fpr
    reasons["target_fpr"] = "reason.target_fpr"
    if _eval_views(views):
        # R1 review fix (OR1-pb-7), 2026-11-16: always bound the evaluation. miWorkbench refuses a
        # view above its bound without one, AFTER the approval is consumed (A40), and a view's size
        # is not in the behaviour detail; a bound never changes a smaller view, which is scored whole
        # (``services/eval_sample_size.py:28-43``).
        config["eval_max_rows"] = MAX_UNSAMPLED_ROWS
        reasons["eval_max_rows"] = "reason.eval_rows"
    if expert_config:
        check_expert_config(expert_config, accepted)
        config.update(expert_config)
    body: dict[str, Any] = {
        "model_id": model_id,
        "train_dataset_id": views["train"]["id"],
        "eval_dataset_ids": [v["id"] for v in _eval_views(views)],
        "calibration_dataset_id": views["calibration"]["id"],
        "behaviour": key,
    }
    if config:
        body["config"] = config
    return body, reasons


EVAL_ROLES = ("test", "ood", "everyday_text", "nonsense_text")


def _eval_views(views: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [views[r] for r in EVAL_ROLES if r in views]
