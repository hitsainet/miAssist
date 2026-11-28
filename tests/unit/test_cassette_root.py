"""One cassette format and one root (001 FR-31; A22, M14; FTASKS 4.5).

The published schema file equals the model; every cassette in the tree (by path or by content)
lives under ``tests/fixtures/cassettes/private/``; the writer refuses any other target; the fake
transport serves records in order and refuses anything else.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.support.cassette import (
    FORMAT,
    SCHEMA_FILE,
    Cassette,
    CassetteMiss,
    CassetteRoot,
    CassetteTransport,
    schema_text,
    strip_answer_headers,
    strip_request_headers,
)
from tests.support.cassette_scan import CASSETTE_ROOT, all_cassettes

ROOT = Path(__file__).resolve().parents[2]


def outside_root(tree: Path) -> list[str]:
    return sorted(
        str(p) for p in all_cassettes(tree) if not str(p).startswith(str(CASSETTE_ROOT) + "/")
    )


def test_schema_file_is_the_model() -> None:
    assert SCHEMA_FILE.read_text() == schema_text(), "run tests.support.cassette.write_schema()"


def test_schema_file_survives_the_mirror_strip() -> None:
    """The schema declares no top-level format. It names the format (its ``const``), so it is
    published only through the strip script's exact ``MAY_NAME_THE_FORMAT`` count (R2 review fix
    OR2-001-5; this file itself must not spell the format, or the mirror refuses it)."""
    assert json.loads(SCHEMA_FILE.read_text()).get("format") is None
    assert f'"format": "{FORMAT}"' not in SCHEMA_FILE.read_text()


def test_every_cassette_under_the_root() -> None:
    assert outside_root(ROOT) == []


def test_plants_outside_the_root_are_found(tmp_path: Path) -> None:
    (tmp_path / "tests/cassettes").mkdir(parents=True)
    (tmp_path / "tests/cassettes/x.cassette.json").write_text("{}")
    (tmp_path / "tests/fixtures/data").mkdir(parents=True)
    (tmp_path / "tests/fixtures/data/y.json").write_text(json.dumps({"format": FORMAT}))
    (tmp_path / CASSETTE_ROOT / "miforge").mkdir(parents=True)
    (tmp_path / CASSETTE_ROOT / "miforge/ok.cassette.json").write_text("{}")
    assert outside_root(tmp_path) == [
        "tests/cassettes/x.cassette.json",
        "tests/fixtures/data/y.json",
    ]


@pytest.mark.parametrize(
    "relative",
    ["../x.cassette.json", "/tmp/x.cassette.json", "miforge/x.json", "../../tests/x.cassette.json"],
)
def test_writer_refuses_outside_the_root(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="cassette_outside_root"):
        CassetteRoot(tmp_path / "private").target(relative)


def test_header_stripping() -> None:
    sent = {
        "X-Miforge-Agent": "agent:miassist",
        "Authorization": "Bearer test-only",
        "X-MiStudio-Approval-Request": "a1",
        "Cookie": "c",
    }
    assert strip_request_headers("miforge", sent) == {
        "X-Miforge-Agent": "agent:miassist",
        "X-MiStudio-Approval-Request": "a1",
    }
    got = {"X-MiStudio-Approval": "pending", "Set-Cookie": "s", "Server": "x"}
    assert strip_answer_headers(got) == {"X-MiStudio-Approval": "pending"}


def record(seq: int, path: str, route: str, body: object) -> dict[str, object]:
    return {
        "seq": seq,
        "app": "miforge",
        "app_version": "0.5.0",
        "time": "2026-11-16T05:00:00-05:00",
        "request": {"method": "GET", "path": path, "route": route, "query": {}},
        "answer": {"status": 200, "body": body},
    }


def test_transport_serves_in_order_and_misses_loudly() -> None:
    cassette = Cassette.model_validate(
        {
            "format": FORMAT,
            "name": "fixture-order",
            "source": "hand_written",
            "records": [
                record(
                    1, "/api/v1/approvals/evalfx-2", "/api/v1/approvals/{approval_id}", {"n": 2}
                ),
                record(
                    0, "/api/v1/approvals/evalfx-1", "/api/v1/approvals/{approval_id}", {"n": 1}
                ),
            ],
        }
    )
    transport = CassetteTransport(cassette, "miforge", ["/api/v1/approvals/{approval_id}"])
    with httpx.Client(base_url="http://f.test", transport=transport) as client:
        assert client.get("/api/v1/approvals/evalfx-1").json() == {"n": 1}
        with pytest.raises(CassetteMiss):
            client.get("/api/v1/approvals/evalfx-9")
        assert client.get("/api/v1/approvals/evalfx-2").json() == {"n": 2}
        with pytest.raises(CassetteMiss):
            client.get("/api/v1/approvals/evalfx-2")


def test_format_name_allow_list_is_exact() -> None:
    """R2 review fix (OR2-001-5): each file the mirror lets name the format is listed with exactly
    the count it has, so one more mention (an appended record) refuses the publish."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cassette_strip", ROOT / ".github/scripts/cassette_strip.py"
    )
    assert spec is not None and spec.loader is not None
    strip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strip)
    assert strip.MAY_NAME_THE_FORMAT, "the format's model and schema are published"
    for rel, allowed in strip.MAY_NAME_THE_FORMAT.items():
        assert strip.name_count((ROOT / rel).read_bytes()) == allowed, rel
