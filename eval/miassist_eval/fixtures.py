"""The fixture registry (FR-002.14a; FTID §3.17; FTDD §4.4a).

``fixtures create`` and ``fixtures check`` talk to live apps and run only by hand on the
workstation (FTASKS 3.2b); this module's pure part loads and validates ``eval/fixtures.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from miassist_eval import schemas

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
FIXTURES_PATH = EVAL_ROOT / "fixtures.yaml"
PREFIX = "evalfx-"
#: The agent header a fixture creation sends, naming the evaluation (FTID §3.17): miWorkbench's
#: pattern refuses a colon.
CREATOR_HEADERS = {
    "miworkbench": ("X-MiStudio-Agent", "eval-fixtures"),
    "miserver": ("X-miLLM-Agent", "agent:eval-fixtures"),
    "midataworks": ("X-Dataworks-Agent", "agent:eval-fixtures"),
    "miforge": ("X-Miforge-Agent", "agent:eval-fixtures"),
}


@dataclass(frozen=True)
class Registry:
    raw: dict[str, Any]

    @property
    def fixtures(self) -> list[dict[str, Any]]:
        fixtures: list[dict[str, Any]] = self.raw["fixtures"]
        return fixtures

    @property
    def keys(self) -> set[str]:
        return {f["key"] for f in self.fixtures}

    def allowed_values(self) -> set[str]:
        """Every value a run of a goal may name at the start: keys, names, app ids, repo ids."""
        out: set[str] = set()
        for f in self.fixtures:
            for field in ("key", "name", "app_id", "repo_id"):
                if f.get(field):
                    out.add(str(f[field]))
        return out

    def not_created(self) -> list[str]:
        return [f["key"] for f in self.fixtures if not f.get("app_id")]


def check(raw: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    found = schemas.errors("eval-fixtures", raw)
    if found:
        return found
    keys = [f["key"] for f in raw["fixtures"]]
    found += [f"duplicate fixture key {k}" for k in sorted({k for k in keys if keys.count(k) > 1})]
    for f in raw["fixtures"]:
        if f["origin"] == "synthetic" and not (repo_root / f["made_from"]).is_file():
            found.append(f"{f['key']}: made_from {f['made_from']} does not exist")
    ids = {str(f["app_id"]) for f in raw["fixtures"] if f.get("app_id")}
    if set(map(str, raw.get("ids", []))) != ids:
        found.append("ids must list exactly the fixtures' app ids (Core's recorder reads it)")
    repos = {str(f["repo_id"]) for f in raw["fixtures"] if f.get("repo_id")}
    if set(map(str, raw.get("public_repositories", []))) != repos:
        found.append("public_repositories must list exactly the fixtures' repo ids")
    return found


def load(path: Path = FIXTURES_PATH) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    found = check(raw)
    if found:
        raise ValueError("fixtures: " + "; ".join(found))
    return Registry(raw)
