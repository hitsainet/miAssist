"""The ONE id-filter rule (001 FR-31; A22, A37, R2M-7; FTASKS 4.5).

``tests/fixtures/id_filter_vectors.json`` runs through BOTH entry points: the rule itself
(``AllowedSet.check_request``) and Core's recorder (``scripts.record_cassettes.Recorder``, whose
request-time check must refuse before anything is sent). 002's recording proxy imports the same
objects (``::test_002_imports_the_rule`` skips loudly until 002-P1 exists). The rule's package
imports nothing from ``miassist``. A secret in a finished cassette stops the write.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import httpx
import miassist_fixtures.filter as rule
import pytest
from miassist_fixtures.filter import (
    AllowedSet,
    FixtureRefused,
    RouteProfile,
    filter_list,
    final_scan,
)
from scripts.record_cassettes import Recorder, write

from tests.support.cassette import FORMAT, CassetteRoot

ROOT = Path(__file__).resolve().parents[2]
TABLE = json.loads((ROOT / "tests/fixtures/id_filter_vectors.json").read_text())
VECTORS = TABLE["vectors"]


def allowed() -> AllowedSet:
    fx = TABLE["fixtures"]
    return AllowedSet(
        prefix=fx["prefix"], ids=set(fx["ids"]), repositories=set(fx["public_repositories"])
    )


def profile(vector: dict[str, Any]) -> RouteProfile:
    return RouteProfile(vector["profile"]["template"], creates=vector["profile"]["creates"])


def verdict_by_rule(vector: dict[str, Any]) -> tuple[str, str | None]:
    try:
        allowed().check_request(profile(vector), vector["request"])
    except FixtureRefused as refused:
        return "refused", refused.where
    return "allowed", None


def verdict_by_recorder(vector: dict[str, Any]) -> tuple[str, str | None, int]:
    sent: list[httpx.Request] = []

    def app(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"id": "evalfx-created"})

    recorder = Recorder("midataworks", httpx.MockTransport(app), allowed(), [profile(vector)])
    req = vector["request"]
    method = "POST" if req["body"] is not None else "GET"
    with httpx.Client(base_url="http://fixture.test", transport=recorder.transport()) as client:
        try:
            client.request(method, req["path"], params=req["query"], json=req["body"])
        except FixtureRefused as refused:
            return "refused", refused.where, len(sent)
    return "allowed", None, len(sent)


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vectors(vector: dict[str, Any]) -> None:
    """Entry point 1: the rule itself."""
    assert verdict_by_rule(vector) == (vector["verdict"], vector["refused_at"])


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vectors_through_the_recorder(vector: dict[str, Any]) -> None:
    """Entry point 2: Core's recorder, whose request-time check refuses before sending."""
    verdict, where, sent = verdict_by_recorder(vector)
    assert (verdict, where) == (vector["verdict"], vector["refused_at"])
    assert sent == (1 if verdict == "allowed" else 0), "a refused request must not be sent"


def test_both_verdicts_and_every_field_kind_covered() -> None:
    assert {v["verdict"] for v in VECTORS} == {"allowed", "refused"}
    refused = {v["refused_at"].split(".")[-1].split("[")[0] for v in VECTORS if v["refused_at"]}
    assert {"dataset_id", "eval_dataset_ids", "key", "repo_id", "name", "path"} <= refused


def test_002_imports_the_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    # R2 review fix (OR2-int-4), 2026-11-16: 002's package is ``eval/miassist_eval``; the old path
    # (``ROOT/miassist_eval``) never existed, so this skipped on every head. It skips only while
    # ``eval/`` itself is absent (before 002-P1); once ``eval/`` exists a missing module FAILS.
    allowed_py = ROOT / "eval" / "miassist_eval" / "allowed.py"
    if not (ROOT / "eval").is_dir():
        pytest.skip("002-P1 not built: eval/ does not exist yet (V-9)")
    assert allowed_py.is_file(), "eval/ exists but eval/miassist_eval/allowed.py does not"
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    import importlib

    theirs = importlib.import_module("miassist_eval.allowed")
    for name in ("AllowedSet", "filter_list", "final_scan"):
        assert getattr(theirs, name) is getattr(rule, name), name


def test_exports() -> None:
    assert {"AllowedSet", "filter_list", "final_scan"} <= set(rule.__all__)


def imports_of(source: str) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            out.add(str(node.args[0].value).split(".")[0])
    return out


def test_no_server_imports() -> None:
    for path in sorted((ROOT / "miassist_fixtures").rglob("*.py")):
        assert "miassist" not in imports_of(path.read_text()), path
    assert "miassist" in imports_of("from miassist.adapters import base\n")
    assert "miassist" in imports_of("import importlib\nimportlib.import_module('miassist.x')\n")


def test_recorder_filters_list_answers() -> None:
    def app(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [{"name": "evalfx-pack"}, {"name": "theirs"}]})

    recorder = Recorder(
        "miforge", httpx.MockTransport(app), allowed(), [RouteProfile("/api/v1/packs")]
    )
    with httpx.Client(base_url="http://fixture.test", transport=recorder.transport()) as client:
        client.get("/api/v1/packs")
    assert recorder.records[0]["answer"]["body"] == {"items": [{"name": "evalfx-pack"}]}
    assert final_scan(recorder.cassette("x"), allowed()) == []


def test_filter_list_keeps_fixture_items_only() -> None:
    answer = {
        "items": [{"id": "evalfx-1", "name": "evalfx-one"}, {"id": "prod-9", "name": "theirs"}],
        "total": 2,
    }
    assert filter_list(answer, allowed()) == {
        "items": [{"id": "evalfx-1", "name": "evalfx-one"}],
        "total": 2,
    }


def test_final_scan_finds_what_is_left() -> None:
    cassette = {
        "records": [
            {
                "seq": 0,
                "request": {"route": "/a/{x}", "path": "/a/prod-1", "query": {}, "body": None},
                "answer": {"body": {"items": [{"id": "prod-2"}]}},
            }
        ]
    }
    assert final_scan(cassette, allowed()) == [
        "records[0].request.path.x",
        "records[0].answer.items[0].id",
    ]


def cassette_with(body: Any) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "name": "fixture-write",
        "source": "recorded",
        "records": [
            {
                "seq": 0,
                "app": "miforge",
                "app_version": "0.5.0",
                "time": "2026-11-16T05:00:00-05:00",
                "request": {"method": "GET", "path": "/api/v1/packs", "route": "/api/v1/packs"},
                "answer": {"status": 200, "body": body},
            }
        ],
    }


def test_secret_stops_write(tmp_path: Path) -> None:
    root = CassetteRoot(tmp_path / "private")
    written = write(
        cassette_with([{"name": "evalfx-pack"}]), "miforge/ok.cassette.json", allowed(), root
    )
    assert written.is_file()
    leaky = cassette_with(
        [
            {
                "name": "evalfx-pack",
                "note": "HF_" + "TOKEN=" + "hf_" + "abcdefghijklmnopqrstuvwxyz123456",
            }
        ]
    )
    with pytest.raises(ValueError, match="secret_found"):
        write(leaky, "miforge/leak.cassette.json", allowed(), root)
    assert not (tmp_path / "private/miforge/leak.cassette.json").exists()


def test_foreign_value_stops_write(tmp_path: Path) -> None:
    root = CassetteRoot(tmp_path / "private")
    with pytest.raises(FixtureRefused):
        write(
            cassette_with([{"name": "someone-elses"}]), "miforge/x.cassette.json", allowed(), root
        )
    assert not list((tmp_path / "private").rglob("*.json"))


def planted() -> str:
    """A credential-like value, built at run time so this file carries none (the tracked scan)."""
    return "s3cr3t" + "value42abc"


def passphrase() -> str:
    return "the horse " + "battery staple"


#: R2 review fix (OR2-001-2), 2026-11-16: a credential-named key holding a value refuses the write,
#: whatever its case, separators or escaping, and wherever it sits (answer body, request body,
#: query, a nested JSON string or a query string inside a value). Each value would pass the text
#: scanner's shape rules.
CREDENTIAL_BODIES: list[tuple[str, Any]] = [
    ("token", {"token": planted()}),
    ("hf_token", {"hf_token": planted()}),
    ("password", {"password": passphrase()}),
    ("secret", {"secret": planted()}),
    ("api_key", {"api_key": planted()}),
    ("authorization", {"authorization": "Bearer " + planted()}),
    ("upper", {"HF_TOKEN": planted()}),
    ("camel", {"apiKey": planted()}),
    ("hyphen", {"X-Api-Key": planted()}),
    ("title", {"Authorization": "Basic " + planted()}),
    ("suffix", {"client_secret": planted()}),
    ("url-encoded key", {"hf%5Ftoken": planted()}),
    ("html-encoded key", {"pass&#119;ord": planted()}),
    ("nested", {"settings": {"hub": {"token": planted()}}}),
    ("in a list", [{"name": "evalfx-pack", "token": planted()}]),
    ("json in a string", {"name": "evalfx-pack", "note": json.dumps({"pass" + "word": planted()})}),
    ("query in a string", {"name": "evalfx-pack", "url_query": "a=1&tok" + "en=" + planted()}),
    ("number", {"pin_password": int("1234" + "56")}),
    ("nested value", {"secret": {"value": planted()}}),
    # R3 review fix (OR3-001-5), 2026-11-16: more credential key names, any case, and a bearer
    # credential under any key
    ("secret_key", {"secret_key": planted()}),
    ("access_key", {"aws": {"access_key": planted()}}),
    ("aws_secret_access_key", {"AWS_SECRET_ACCESS_KEY": planted()}),
    ("pwd", {"pwd": planted()}),
    ("PWD", {"DB_PWD": planted()}),
    ("auth", {"auth": planted()}),
    ("x-auth", {"X-Auth": planted()}),
    ("cookie", {"cookie": "session=" + planted()}),
    ("Cookie", {"Cookie": "session=" + planted()}),
    ("bearer under note", {"name": "evalfx-pack", "note": "Bearer " + planted()}),
    ("bearer lower", {"name": "evalfx-pack", "header": "bearer " + planted()}),
    # Confirmation fix (C-001-4), 2026-11-16: a bearer credential in prose or a header line, a
    # header list ([name, value] pairs and HAR-style name/value mappings) and JSON text encoded
    # again as a JSON string. Each is seen by the key check itself, not only the text scan.
    ("bearer in prose", {"name": "evalfx-pack", "note": "send Authorization: Bearer " + planted()}),
    ("bearer list item", {"name": "evalfx-pack", "headers": ["Bearer " + planted()]}),
    ("header pair", {"name": "evalfx-pack", "headers": [["X-Api-Key", planted()]]}),
    (
        "header name/value",
        {
            "name": "evalfx-pack",
            "headers": [{"header": "Authorization", "value": "Basic " + planted()}],
        },
    ),
    (
        "json in json text",
        {"name": "evalfx-pack", "note": json.dumps(json.dumps({"pass" + "word": planted()}))},
    ),
    (
        "escaped json text",
        {
            "name": "evalfx-pack",
            "note": json.dumps({"pass" + "word": planted()}).replace('"', '\\"'),
        },
    ),
]


@pytest.mark.parametrize(
    "body", [b for _, b in CREDENTIAL_BODIES], ids=[i for i, _ in CREDENTIAL_BODIES]
)
def test_credential_key_stops_write(tmp_path: Path, body: Any) -> None:
    root = CassetteRoot(tmp_path / "private")
    with pytest.raises(ValueError, match="secret_found: a credential-named key") as caught:
        write(cassette_with(body), "miforge/leak.cassette.json", allowed(), root)
    assert "s3cr3t" not in str(caught.value) and "horse" not in str(caught.value)
    assert not list((tmp_path / "private").rglob("*.json"))


def test_credential_key_in_the_request_stops_write(tmp_path: Path) -> None:
    cassette = cassette_with([{"name": "evalfx-pack"}])
    cassette["records"][0]["request"]["query"] = {"Hf-Token": planted()}
    with pytest.raises(ValueError, match="secret_found"):
        write(cassette, "miforge/q.cassette.json", allowed(), CassetteRoot(tmp_path))


@pytest.mark.parametrize(
    "body",
    [
        [{"name": "evalfx-pack", "token": None}],
        [{"name": "evalfx-pack", "token": ""}],
        [{"name": "evalfx-pack", "hf_token_set": True, "has_token": False}],
        [{"name": "evalfx-pack", "max_tokens": 512, "tokens_used": 3, "tokenizer": "bpe"}],
        [{"name": "evalfx-pack", "eos_token": "</s>", "bos_token": "<s>", "pad_token": "<pad>"}],
        [{"name": "evalfx-pack", "author": "fixture", "auth_mode": "none", "requires_auth": True}],
        [{"name": "evalfx-pack", "cookie_policy": "none", "note": "the bearer of good news"}],
        [
            {
                "name": "evalfx-pack",
                "note": "authenticate with a Bearer <token> header",
                "how": "for example, Authorization: Bearer example-token-12345678",
                "headers": [["content-type", "json"], {"header": "accept", "value": "json"}],
                "pair": ["token", ""],
                "doc": json.dumps(json.dumps({"name": "evalfx-pack"})),
            }
        ],
    ],
    ids=[
        "null",
        "empty",
        "flags",
        "counts",
        "tokenizer-vocabulary",
        "auth-words",
        "cookie-words",
        "header-lists-and-prose",
    ],
)
def test_carrying_no_credential_is_written(tmp_path: Path, body: Any) -> None:
    """The control: the same write with a key that names no credential, or one holding nothing."""
    root = CassetteRoot(tmp_path / "private")
    assert write(cassette_with(body), "miforge/ok.cassette.json", allowed(), root).is_file()


#: R3 review fix (OR3-001-4), 2026-11-16 (the reviewer's proposed test): a credential-SHAPED value
#: under a key that names no credential is seen only by the recorder's text scan (``scan_text`` in
#: ``write``), which must refuse the write. Each value is built at run time (the tracked scan).
SHAPED_VALUES: list[tuple[str, Any]] = [
    ("hf shape", {"name": "evalfx-pack", "note": "hf_" + "A" * 34}),
    (
        "url with credentials",
        {"name": "evalfx-pack", "endpoint": "https://user:" + planted() + "@host/x"},
    ),
    ("anthropic shape", {"name": "evalfx-pack", "note": "sk-ant-" + "x1" * 20}),
]


@pytest.mark.parametrize("body", [b for _, b in SHAPED_VALUES], ids=[i for i, _ in SHAPED_VALUES])
def test_a_credential_shaped_value_refuses_the_write(tmp_path: Path, body: Any) -> None:
    root = CassetteRoot(tmp_path / "private")
    from scripts.record_cassettes import credential_keys

    assert credential_keys(cassette_with(body)) == [], "seen by the key check, not the text scan"
    with pytest.raises(ValueError, match="secret_found: the cassette was not written"):
        write(cassette_with(body), "miforge/leak.cassette.json", allowed(), root)
    assert not list((tmp_path / "private").rglob("*.json"))
