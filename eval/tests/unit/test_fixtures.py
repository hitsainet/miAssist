"""FR-002.14a: fixtures under the prefix, with origin, licence and source file."""

from __future__ import annotations

import json

import pytest
import yaml

from miassist_eval import fixtures


def raw() -> dict:
    return yaml.safe_load(fixtures.FIXTURES_PATH.read_text())


def test_the_committed_registry_validates() -> None:
    reg = fixtures.load()
    assert all(k.startswith("evalfx-") for k in reg.keys)


@pytest.mark.parametrize(
    ("mutate", "why"),
    [
        (lambda f: f.pop("origin"), "origin"),
        (lambda f: f.__setitem__("key", "refund-messages"), "prefix on the key"),
        (lambda f: f.__setitem__("name", "refund-messages"), "prefix on the creator's name"),
    ],
)
def test_bad_synthetic_entry_fails(mutate, why: str) -> None:
    doc = raw()
    mutate(doc["fixtures"][0])
    assert fixtures.check(doc), f"no error for a missing {why}"


def test_public_without_licence_fails() -> None:
    doc = raw()
    public = next(f for f in doc["fixtures"] if f["origin"] == "public")
    public.pop("licence")
    assert fixtures.check(doc)


def test_synthetic_needs_its_file() -> None:
    doc = raw()
    doc["fixtures"][0]["made_from"] = "eval/fixtures/data/missing.jsonl"
    assert any("does not exist" in f for f in fixtures.check(doc))


def test_core_reader_lists_agree_with_the_fixtures() -> None:
    doc = raw()
    doc["public_repositories"].append("someone/private-repo")
    assert any("public_repositories" in f for f in fixtures.check(doc))


def test_core_reads_the_same_file() -> None:
    """Core's AllowedSet.from_fixtures reads prefix, ids and public repositories from this file."""
    from miassist_eval import allowed

    allowed_set = allowed.AllowedSet.from_fixtures(fixtures.FIXTURES_PATH)
    assert allowed_set.prefix == "evalfx-"
    assert allowed_set.repositories == {"Salesforce/wikitext", "Qwen/Qwen2.5-0.5B-Instruct"}


def test_synthetic_messages_are_labelled_and_invented() -> None:
    path = fixtures.REPO_ROOT / "eval/fixtures/data/refund_messages.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert {r["label"] for r in rows} == {"refund", "other"}
    assert all(r["id"].startswith("evalfx-") for r in rows)
    assert sum(r["label"] == "refund" for r in rows) >= 20
