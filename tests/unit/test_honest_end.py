"""The honest end (001 FR-28, AC-28.1; FTASKS 11.8)."""

from __future__ import annotations

import pytest

from miassist.adapters.base import ProgrammingError
from miassist.results.honest_end import honest_end

FORBIDDEN = ("error", "warning", "fail", "refus", "cannot", "unable")


@pytest.mark.parametrize(
    "apps,installed,expected",
    [
        (["miserver"], ["midataworks"], "needs miServer, which isn't part of this installation"),
        (
            ["miforge", "miserver"],
            ["midataworks"],
            "needs miServer or miForge, which aren't part of this installation",
        ),
        (
            ["miforge", "miworkbench", "miserver"],
            [],
            "needs miWorkbench, miServer or miForge, which aren't part of this installation",
        ),
    ],
    ids=["one", "two", "three"],
)
def test_vectors(apps: list[str], installed: list[str], expected: str) -> None:
    sentence = honest_end(apps, installed)
    assert sentence == expected
    for word in FORBIDDEN:
        assert word not in sentence.lower()


@pytest.mark.parametrize("apps", [["miserver"], ["miserver", "miforge"]])
def test_installed_app_refused(apps: list[str]) -> None:
    with pytest.raises(ProgrammingError, match="absent apps only"):
        honest_end(apps, ["miserver"])


@pytest.mark.parametrize("apps", [[], ["nope"], ["miserver", "miserver"]])
def test_malformed_ids_refused(apps: list[str]) -> None:
    with pytest.raises(ProgrammingError):
        honest_end(apps, [])
