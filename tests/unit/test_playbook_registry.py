"""The playbook registry (001 FR-5, AC-5.1, AC-5.2, AC-5.7, AC-5.8; FTASKS 11.1, 11.2).

A definition that fails the schema, names an unregistered tool in a step it does not skip, repeats
an id, or names a text key its words file lacks refuses start, naming the file, the field and the
key. The offering rule is pinned by ``tests/fixtures/offering_vectors.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from miassist.contracts.playbook import Playbook
from miassist.guidance.loader import Guidance
from miassist.playbooks.registry import PlaybookError, load, resolve
from miassist.tools import CORE_SPECS, all_specs
from tests.support.playbook_copies import (
    FIXTURE_WORDS,
    copy_guidance,
    definition,
    fixture_definition,
    write_definition,
    write_words,
)

ALL = ("miworkbench", "miserver", "midataworks", "miforge")
CORE_TOOLS = frozenset(s.name for s in CORE_SPECS)
ALL_TOOLS = frozenset(s.name for s in all_specs())  # Core's and the playbook chains' tools
VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/offering_vectors.json").read_text()
)["vectors"]


@pytest.fixture(scope="module")
def words(tmp_path_factory: pytest.TempPathFactory) -> Guidance:
    root = copy_guidance(tmp_path_factory.mktemp("words"))
    write_words(root, "fixture-pb", FIXTURE_WORDS)
    return Guidance(root)


def test_shipped_definitions_load_and_resolve() -> None:
    registry = load(Guidance(), ALL, ALL_TOOLS)
    assert {(p.id, p.version) for p in registry.playbooks.values()} == {
        (f"start-{app}", 1) for app in ALL
    } | {("detector-probe", 1), ("dataset", 1), ("steering", 1)}
    for playbook in (p for p in registry.playbooks.values() if p.id.startswith("start-")):
        assert playbook.offered and playbook.title and playbook.goal
        assert [s.id for s in playbook.steps] == ["look-around", "learn-a-word", "what-next"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_offering_vectors(vector: dict[str, Any], words: Guidance) -> None:
    playbook = Playbook.model_validate(vector["definition"])
    resolved = resolve(playbook, words, frozenset(vector["installed"]), CORE_TOOLS, "fixture")
    assert resolved.offered is vector["offered"]
    assert resolved.not_in_this_installation == vector["skipped"]
    assert list(resolved.needs) == vector["needs"]


def _break(data: dict[str, Any], case: str) -> tuple[dict[str, Any], str]:
    """Each refusal case: the broken definition and the text the refusal must name."""
    steps = data["steps"]
    if case == "schema":
        data["colour"] = "red"
        return data, "fixture-pb.json at colour"
    if case == "unregistered-tool":
        steps[1]["tool"] = "miassist_not_here"
        return data, "fixture-pb.json at steps.1.tool: 'miassist_not_here'"
    if case == "repeated-step-id":
        steps[1]["id"] = "one"
        return data, "fixture-pb.json at steps.1.id: repeats 'one'"
    if case == "no-entry-step":
        steps[0].pop("entry")
        return data, "fixture-pb.json at steps: no step has entry: true"
    if case == "value-missing":
        steps[0]["done_when"]["op"] = "equals"
        return data, "fixture-pb.json at steps.0.done_when.value: required"
    if case == "value-not-allowed":
        steps[0]["done_when"]["value"] = 1
        return data, "fixture-pb.json at steps.0.done_when.value: not allowed"
    if case == "unresolved-key":
        steps[1]["explain_beginner"] = "two.nowhere"
        return data, (
            "fixture-pb.json at steps.1.explain_beginner: the key 'two.nowhere' is not in "
            "guidance/playbooks/fixture-pb.yaml"
        )
    if case == "unresolved-title":
        data["title"] = "playbook.nowhere"
        return data, "fixture-pb.json at title: the key 'playbook.nowhere' is not in"
    if case == "wrong-file-name":
        return data, "wrong-name.json at id: the file must be fixture-pb.json"
    if case == "no-words-file":
        data["id"] = "fixture-nowords"
        return data, "no words file guidance/playbooks/fixture-nowords.yaml"
    raise AssertionError(case)


REFUSALS = [
    "schema",
    "unregistered-tool",
    "repeated-step-id",
    "no-entry-step",
    "value-missing",
    "value-not-allowed",
    "unresolved-key",
    "unresolved-title",
    "wrong-file-name",
    "no-words-file",
]


@pytest.mark.parametrize("case", REFUSALS)
def test_invalid_definition_refuses(case: str, tmp_path: Path, words: Guidance) -> None:
    folder = tmp_path / "definitions"
    folder.mkdir()
    data, named = _break(fixture_definition(), case)
    write_definition(folder, data, "wrong-name.json" if case == "wrong-file-name" else None)
    with pytest.raises(PlaybookError) as refused:
        load(words, ("miforge",), CORE_TOOLS, folder)
    assert str(refused.value).startswith("playbook_invalid: "), refused.value
    assert named in str(refused.value), refused.value


def test_unregistered_tool_in_a_skipped_step_is_allowed(tmp_path: Path, words: Guidance) -> None:
    data = fixture_definition(requires=["miforge", "miserver"])
    data["steps"][1]["tool"] = "miassist_not_here"
    data["steps"][1]["requires_apps"] = ["miserver"]
    folder = tmp_path / "definitions"
    folder.mkdir()
    write_definition(folder, data)
    registry = load(words, ("miforge",), CORE_TOOLS, folder)
    assert registry.playbooks["fixture-pb"].not_in_this_installation == ["two"]


def test_resolved_text_bounds(tmp_path: Path) -> None:
    root = copy_guidance(tmp_path)
    write_words(root, "fixture-pb", {**FIXTURE_WORDS, "playbook.title": "x" * 81})
    folder = tmp_path / "definitions"
    folder.mkdir()
    write_definition(folder, fixture_definition())
    with pytest.raises(PlaybookError, match="81 characters, outside 1-80 for title"):
        load(Guidance(root), ("miforge",), CORE_TOOLS, folder)


def test_markers_resolve_to_terms(words: Guidance) -> None:
    registry = load(words, ALL, ALL_TOOLS)
    forge = registry.playbooks["start-miforge"]
    assert "[[" not in json.dumps([s.explain_beginner for s in forge.steps])
    assert {"pack", "checkpoint"} <= set(forge.terms)


def test_start_here_definitions_are_their_apps(words: Guidance) -> None:
    """11.2: each start-here playbook lists its one app, is read-only, and its steps carry the
    arguments their ``done_when`` needs."""
    expected_terms = {
        "miworkbench": "probe",
        "miserver": "served model",
        "midataworks": "dataset version",
        "miforge": "pack",
    }
    for app, term in expected_terms.items():
        data = definition(f"start-{app}")
        assert data["requires_apps"] == [app]
        steps = {s["id"]: s for s in data["steps"]}
        assert steps["look-around"]["tool"] == "miassist_overview"
        assert steps["look-around"]["args"] == {"app": app} and steps["look-around"]["entry"]
        assert steps["look-around"]["done_when"] == {
            "description": "look-around.done",
            "pointer": "/app",
            "op": "equals",
            "value": app,
        }
        assert steps["learn-a-word"]["args"] == {"term": term}
        assert steps["learn-a-word"]["done_when"]["pointer"] == "/entry"
        assert steps["what-next"]["args"] == {"topic": "playbooks"}
        assert steps["what-next"]["done_when"]["pointer"] == "/playbooks"
        read_only = {s.name for s in CORE_SPECS if s.read_only}
        assert {s["tool"] for s in data["steps"]} <= read_only
