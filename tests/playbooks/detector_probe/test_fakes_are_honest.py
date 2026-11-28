"""The fakes' honesty check is wired (R1 review fix OR1-pb-6 to OR1-pb-9, 2026-11-16): the three
detector fakes are checked fakes, a checked fake records an answer the app never sends, and this
directory's conftest turns that record into a failing test."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from miassist.adapters.base import HEADERS
from tests.playbooks.detector_probe import fakes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def test_the_three_detector_fakes_are_checked() -> None:
    made = fakes.fakes_for(fakes.World())
    for app in ("miworkbench", "midataworks", "miserver"):
        assert isinstance(made[app], fakes.CheckedFake), app
        assert made[app] in fakes.CREATED


def _ask(fake: fakes.CheckedFake, path: str) -> None:
    name, value = HEADERS[fake.app]
    fake.handle(httpx.Request("GET", f"http://fake{path}", headers={name: value}))


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"selected_probe_id": "p"}, "$.selected_probe_id: invented"),
        ({"status": "refused"}, "$.status: 'refused' is not one of"),
    ],
)
def test_a_checked_fake_records_an_answer_the_app_never_sends(answer: Any, expected: str) -> None:
    world = fakes.World()
    fake = fakes.workbench(world)
    run = {"id": "evalfx-run-1", "status": "pending", "config": {}, "environment": {}}
    world.runs["evalfx-run-1"] = {**run, **answer}
    _ask(fake, f"{fakes.PM}/runs/evalfx-run-1")
    found = fake.shape_violations
    fakes.CREATED.remove(fake)
    assert any(expected in v for v in found), found


def test_a_dropped_field_is_recorded() -> None:
    fake = fakes.workbench(fakes.World())
    fake.on("GET", "/api/v1/task-queue/lookup/{task_id}", lambda r: {"task_id": "t", "found": []})
    _ask(fake, "/api/v1/task-queue/lookup/t")
    found = fake.shape_violations
    fakes.CREATED.remove(fake)
    assert found == [
        "miworkbench GET /api/v1/task-queue/lookup/{task_id} 200: $.searched: dropped "
        "(the app always sends it)"
    ]


INVENTED = """
from tests.playbooks.detector_probe import fakes

def test_it():
    fake = fakes.workbench(fakes.World())
    fake.shape_violations.append("miworkbench GET /x 200: $.made_up: invented")
"""


@pytest.mark.parametrize("violation", [True, False])
def test_the_conftest_fails_a_test_whose_fake_departed(tmp_path: Path, violation: bool) -> None:
    """Runs this directory's real conftest over a one-test module in a fresh pytest process."""
    (tmp_path / "conftest.py").write_text((HERE / "conftest.py").read_text())
    body = INVENTED if violation else INVENTED.replace("    fake.shape_violations.append", "    # ")
    (tmp_path / "test_one.py").write_text(body)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "."],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if violation:
        assert done.returncode != 0 and "$.made_up: invented" in done.stdout, done.stdout
    else:
        assert done.returncode == 0, done.stdout
