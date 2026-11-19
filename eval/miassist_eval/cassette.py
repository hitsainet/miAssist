"""Takes: one ``cassette.json`` in Core's ``miassist.cassette/v1`` plus this feature's integrity
wrappers, the take's ``MANIFEST.json`` and the append-only ``INDEX.json`` (FR-002.9, FR-002.13,
FR-002.14, FR-002.14d; FTDD §4.4; FTID §3.2; A22).

Layout: ``tests/fixtures/cassettes/private/eval/<goal>/<surface>/<take>/`` holding
``MANIFEST.json``, ``cassette.json``, ``openapi/<app>.sha256``, ``health/<app>.json`` and
``recording/run.json`` (the recording run's record, so "its run record exists" is checkable inside
the take; OVN-miassist-eval-8).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from miassist_eval import classes, schemas
from miassist_eval.canonical import dumps, sha256_bytes, sha256_file
from miassist_eval.classes import Refusal

REPO_ROOT = Path(__file__).resolve().parents[2]
CASSETTE_ROOT = REPO_ROOT / "tests" / "fixtures" / "cassettes" / "private"
EVAL_CASSETTES = CASSETTE_ROOT / "eval"
FORMAT = "miassist.cassette/v1"
#: Header allow-lists, as Core strips them (FR-002.10).
REQUEST_HEADERS = frozenset(
    {
        "x-mistudio-agent",
        "x-millm-agent",
        "x-dataworks-agent",
        "x-miforge-agent",
        "x-mistudio-approval-request",
    }
)
ANSWER_HEADERS = frozenset({"x-mistudio-approval", "x-millm-approval"})


def require_cassettes() -> bool:
    return os.environ.get("MIASSIST_REQUIRE_CASSETTES") == "1"


@dataclass
class Take:
    path: Path
    manifest: dict[str, Any]
    cassette: dict[str, Any]

    @property
    def cassette_id(self) -> str:
        return str(self.manifest["cassette_id"])

    @property
    def manifest_sha256(self) -> str:
        return sha256_file(self.path / "MANIFEST.json")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def write_take(
    take_dir: Path,
    cassette: dict[str, Any],
    manifest: dict[str, Any],
    run_record: dict[str, Any],
    openapi_hashes: Mapping[str, str],
    health: Mapping[str, Any],
    *,
    allowed_set: Any = None,
    listed: Iterable[str] = (),
) -> Path:
    """Write a take and its manifest (files hashed last). Validates the cassette against Core's
    schema first, so a take that is not Core's format is never written.

    R1 review fix (OR1-002-7), 2026-11-16: this is the ONE choke point every take passes. Before a
    byte is written: Core's ``final_scan`` over the cassette's scan view (JSON and base64 embedded
    at any offset expanded; ``fixture_not_allowed``) against fixture data only unless the caller
    passes the run's set, and the secret scan over every file the take holds, with ``listed``
    values (the run's fresh key) searched raw and encoded (``secret_in_take``)."""
    found = schemas.cassette_errors(cassette)
    if found:
        raise Refusal(classes.CASSETTE_INTEGRITY, "not Core's cassette format: " + found[0])
    from miassist_eval import allowed, secret_scan

    stray = allowed.take_findings(
        cassette, allowed_set if allowed_set is not None else allowed.fixture_set()
    )
    if stray:
        raise Refusal(classes.FIXTURE_NOT_ALLOWED, f"stray ids in the take: {stray[:5]}")
    values = list(listed)
    for label, obj in (
        ("cassette", cassette),
        ("manifest", manifest),
        ("recording run", run_record),
        ("health", health),
    ):
        hits = secret_scan.scan_bytes(json.dumps(obj, sort_keys=True).encode(), values)
        if hits:
            raise Refusal(classes.SECRET_IN_TAKE, f"{label}: {hits}")
    _write_json(take_dir / "cassette.json", cassette)
    _write_json(take_dir / "recording" / "run.json", run_record)
    for app, digest in openapi_hashes.items():
        (take_dir / "openapi").mkdir(parents=True, exist_ok=True)
        (take_dir / "openapi" / f"{app}.sha256").write_text(digest + "\n")
    for app, answer in health.items():
        _write_json(take_dir / "health" / f"{app}.json", answer)
    files = {
        str(p.relative_to(take_dir)): sha256_file(p)
        for p in sorted(take_dir.rglob("*"))
        if p.is_file() and p.name != "MANIFEST.json"
    }
    full = {**manifest, "schema": "miassist.eval-take/v1", "files": files}
    schemas.validate("eval-take", full)
    _write_json(take_dir / "MANIFEST.json", full)
    return take_dir


def read_index(root: Path = EVAL_CASSETTES) -> list[dict[str, Any]]:
    path = root / "INDEX.json"
    if not path.is_file():
        return []
    loaded: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def append_index(root: Path, take: Take, added_utc: str) -> None:
    index = read_index(root)
    if any(e["cassette_id"] == take.cassette_id for e in index):
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{take.cassette_id} is already indexed")
    index.append(
        {
            "cassette_id": take.cassette_id,
            "manifest_sha256": take.manifest_sha256,
            "recording_run_id": take.manifest["recording_run_id"],
            "added_utc": added_utc,
        }
    )
    _write_json(root / "INDEX.json", index)


def index_changes(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[str]:
    """Append-only: an entry may be added, or marked retired (``retired_utc`` and ``reason``
    added), never changed or removed (FR-002.13)."""
    out = []
    now = {e["cassette_id"]: e for e in current}
    for old in previous:
        new = now.get(old["cassette_id"])
        if new is None:
            out.append(f"{old['cassette_id']}: removed from the index")
            continue
        for k, v in old.items():
            if new.get(k) != v:
                out.append(f"{old['cassette_id']}: {k} changed")
        added = set(new) - set(old)
        if added - {"retired_utc", "reason"}:
            out.append(f"{old['cassette_id']}: fields added {sorted(added)}")
    return out


def load(take_dir: Path, index: list[dict[str, Any]] | None = None) -> Take:
    """Verify, then load: files vs MANIFEST, MANIFEST vs INDEX, the recording run record, a passing
    fairness block, and the cassette valid against Core's schema (A22). Any failure refuses
    ``cassette_integrity`` naming the file."""
    manifest_path = take_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{manifest_path}: missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel, digest in manifest.get("files", {}).items():
        path = take_dir / rel
        if not path.is_file():
            raise Refusal(classes.CASSETTE_INTEGRITY, f"{path}: missing")
        if sha256_file(path) != digest:
            raise Refusal(classes.CASSETTE_INTEGRITY, f"{path}: sha256 differs from MANIFEST")
    extra = [
        str(p.relative_to(take_dir))
        for p in take_dir.rglob("*")
        if p.is_file()
        and p.name != "MANIFEST.json"
        and str(p.relative_to(take_dir)) not in manifest.get("files", {})
    ]
    if extra:
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{take_dir}: files not in MANIFEST: {extra}")
    found = schemas.errors("eval-take", manifest)
    if found:
        fair = [f for f in found if f.startswith("fairness")]
        cause = "no passing fairness block" if fair else found[0]
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{manifest_path}: {cause}")
    entries = {e["cassette_id"]: e for e in (index if index is not None else read_index())}
    entry = entries.get(manifest["cassette_id"])
    msha = sha256_file(manifest_path)
    if entry is None or entry.get("retired_utc"):
        raise Refusal(
            classes.CASSETTE_INTEGRITY, f"{manifest_path}: not in INDEX.json (or retired)"
        )
    if entry["manifest_sha256"] != msha:
        raise Refusal(
            classes.CASSETTE_INTEGRITY, f"{manifest_path}: sha256 differs from INDEX.json"
        )
    run_path = take_dir / "recording" / "run.json"
    if not run_path.is_file():
        raise Refusal(
            classes.CASSETTE_INTEGRITY, f"{run_path}: the recording run record is missing"
        )
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("run_id") != manifest["recording_run_id"]:
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{run_path}: not the manifest's recording run")
    cassette = json.loads((take_dir / "cassette.json").read_text(encoding="utf-8"))
    found = schemas.cassette_errors(cassette)
    if found:
        raise Refusal(classes.CASSETTE_INTEGRITY, f"{take_dir / 'cassette.json'}: {found[0]}")
    return Take(take_dir, manifest, cassette)


def strip_headers(headers: Mapping[str, str], allow: frozenset[str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() in allow}


def _get(obj: Any, dotted: str) -> Any:
    node = obj
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def match_values(
    request: Mapping[str, Any], entry: Mapping[str, Any] | None, default_match: list[str]
) -> str:
    """The canonical match values of a request: the profile's ``match`` paths, else
    ``default_match``; ``echo`` fields removed first (TD-10)."""
    entry = entry or {}
    req = {"query": dict(request.get("query") or {}), "body": request.get("body")}
    for dotted in entry.get("echo", []):
        part, _, rest = dotted.partition(".")
        container = req.get(part)
        if isinstance(container, dict) and rest in container:
            container = dict(container)
            container.pop(rest)
            req[part] = container
    paths = entry.get("match") or default_match
    return dumps({p: _get(req, p) if "." in p else req.get(p) for p in paths})


MatchKey = tuple[str, str, str, frozenset[tuple[str, str]], str]


def library(
    cassette: Mapping[str, Any],
    resolve: Any,
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[MatchKey, list[dict[str, Any]]]:
    """Group records into sequences by match key (FTDD §4.4). ``resolve(app, method, path)`` gives
    the reference Route; ``profiles[app]`` the route profile."""
    out: dict[MatchKey, list[dict[str, Any]]] = {}
    for record in sorted(cassette.get("records", []), key=lambda r: r["seq"]):
        req = record["request"]
        app = record["app"]
        route = resolve(app, req["method"], req["path"])
        template = route.template if route is not None else req["route"]
        params = route.params(req["path"]) if route is not None else {}
        entry = route_entry(profiles.get(app, {}), req["method"], template)
        key = (
            app,
            req["method"],
            template,
            frozenset(params.items()),
            match_values(
                req, entry, list(profiles.get(app, {}).get("default_match", ["query", "body"]))
            ),
        )
        out.setdefault(key, []).append(record)
    return out


def route_entry(profile: Mapping[str, Any], method: str, template: str) -> dict[str, Any] | None:
    for r in profile.get("routes", []):
        if r["method"] == method and r["route"] == template:
            return dict(r)
    return None


def find_takes(root: Path = EVAL_CASSETTES) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.rglob("MANIFEST.json"))


def sha_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))
