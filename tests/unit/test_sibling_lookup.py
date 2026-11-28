"""The one sibling lookup's rules (Foundation task 1.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import siblings


def test_variable_wins_even_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "miServer").mkdir()
    monkeypatch.setenv("MISERVER_REPO", str(tmp_path / "nowhere"))
    monkeypatch.delenv("MIASSIST_MISERVER_ROOT", raising=False)
    located = siblings.locate(siblings.MISERVER, base=tmp_path)
    assert located.path == tmp_path / "nowhere"
    assert located.spelling == "MISERVER_REPO"


def test_folder_beside_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in siblings.MIFORGE.env:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "miForge").mkdir()
    assert siblings.locate(siblings.MIFORGE, base=tmp_path).path == tmp_path / "miForge"


def test_absent_skips_without_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in siblings.REQUIRE_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MISERVER_REPO", "/nonexistent/miServer")
    with pytest.raises(pytest.skip.Exception, match="tried MIASSIST_MISERVER_ROOT"):
        siblings.require_root(siblings.MISERVER, "nothing checked")


@pytest.mark.parametrize("switch", siblings.REQUIRE_SWITCHES)
def test_absent_fails_under_switch(monkeypatch: pytest.MonkeyPatch, switch: str) -> None:
    for name in siblings.REQUIRE_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(switch, "1")
    monkeypatch.setenv("MISERVER_REPO", "/nonexistent/miServer")
    with pytest.raises(pytest.fail.Exception, match="cross-repo checks are required"):
        siblings.require_root(siblings.MISERVER, "nothing checked")


def test_four_siblings() -> None:
    assert [s.name for s in siblings.SIBLINGS] == [
        "miWorkbench",
        "miServer",
        "miDataworks",
        "miForge",
    ]
    for sibling in siblings.SIBLINGS:
        assert f"{sibling.name.upper()}_REPO" in sibling.env
        assert f"MIASSIST_{sibling.name.upper()}_ROOT" in sibling.env
