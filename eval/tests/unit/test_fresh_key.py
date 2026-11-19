"""FR-002.23: a fresh per-person key per run in PADR ADR-010's format."""

from __future__ import annotations

import re

from miassist_eval import sut


def test_two_keys_differ_and_match_the_format() -> None:
    a, b = sut.fresh_key(), sut.fresh_key()
    assert a != b
    assert re.fullmatch(r"[a-z2-7]{26}", a) and re.fullmatch(r"[a-z2-7]{26}", b)
    assert sut.miassist_endpoint("http://127.0.0.1:9", a) == f"http://127.0.0.1:9/p/{a}/mcp"


def test_miassist_apps_names_each_listener() -> None:
    env = sut.miassist_env(
        {"miserver": "http://127.0.0.1:2", "midataworks": "http://127.0.0.1:1"}, {}
    )
    assert env["MIASSIST_APPS"] == "midataworks=http://127.0.0.1:1,miserver=http://127.0.0.1:2"


def test_a_baseline_tag_instead_of_a_digest_is_refused(tmp_path) -> None:
    import pytest

    from miassist_eval import classes
    from miassist_eval.classes import Refusal

    lock = tmp_path / "lock.yaml"
    lock.write_text("baseline_images: {miworkbench: 'hitsai/miworkbench-backend:latest'}\n")
    with pytest.raises(Refusal) as caught:
        sut.baseline_images(lock)
    assert caught.value.cls == classes.CLIENT_NOT_STARTED
    lock.write_text(
        "baseline_images: {miworkbench: 'hitsai/miworkbench-backend@sha256:" + "a" * 64 + "'}\n"
    )
    assert sut.baseline_images(lock)


def test_baseline_containers_are_named_for_the_sweep() -> None:
    argv = sut.baseline_run_args("midataworks", "img@sha256:x", "r1", "tok", {"BACKEND_URL": "u"})
    assert argv[argv.index("--name") + 1] == "eval-r1-midataworks"
    assert "MCP_AGENT_IDENTITY=agent:eval-baseline" in argv
