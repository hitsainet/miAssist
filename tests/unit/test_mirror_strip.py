"""The mirror's strip step removes every cassette tree and every non-public ``docs/`` entry, then
REFUSES to publish anything cassette-like that is left (A22, R1M-5, R1M-24; Foundation task 3.7;
R1 review fix OR1-001-3; R2 review fix OR2-001-5, 2026-11-16: fail closed).

Both workflow steps are taken from the PARSED ``sync-to-clean.yml`` and run:

- the strip step in a temporary tree that plants cassette trees (any letter case), a review record
  under ``docs/reviews/``, a file in ``0xcc/`` and the files that must survive, and then each
  refused shape in turn, which must stop the step (exit non-zero) and be named;
- the verify step against a local one-commit "mirror", where a planted leak must set ``FAILED`` and
  a clean mirror must pass (so the red is the leak, not the harness);
- the strip step over a copy of THIS checkout's tracked files, which must publish with nothing but
  the excluded paths removed (no legitimate file is refused or stripped).

This source never spells out the cassette format: every shape is built at run time from the
script's own ``MARK``.
"""

from __future__ import annotations

import base64
import bz2
import gzip
import importlib.util
import io
import json
import lzma
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from tests.support.cassette_scan import CASSETTE_FORMAT, all_cassettes, by_path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/sync-to-clean.yml"
SCRIPT = REPO_ROOT / ".github/scripts/cassette_strip.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cassette_strip", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STRIP = load_script()
#: The full format value, built from the script's own name for it.
MARK: str = STRIP.MARK + "/v1"
CASSETTE = json.dumps({"format": MARK, "records": []})
RECORD = {
    "seq": 0,
    "app": "midataworks",
    "request": {"method": "GET", "path": "/api/v1/models"},
    "answer": {"status": 200, "body": {"name": "operator-secret-model"}},
}


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return buf.getvalue()


def _tar(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        data = text.encode()
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def _png(pixels: bytes, *extra: bytes, level: int = 0, after: bytes = b"") -> bytes:
    """A one-row RGB PNG. Level 0 stores the pixels verbatim in the image data, so a test can put
    exact bytes there (as deflate output can by chance)."""
    pixels += b"\x00" * (-len(pixels) % 3)
    header = struct.pack(">IIBBBBB", len(pixels) // 3, 1, 8, 2, 0, 0, 0)
    image = zlib.compress(b"\x00" + pixels, level)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + b"".join(extra)
        + _chunk(b"IDAT", image[: len(image) // 2])
        + _chunk(b"IDAT", image[len(image) // 2 :])
        + _chunk(b"IEND", b"")
        + after
    )


#: R3 review fix (OR3-001-7), 2026-11-16: the gzip signature by chance in image data, followed by a
#: gzip header and bytes that are not deflate data (block type 3 is reserved), as in the real
#: screenshot the review found (miDataworks' light-label-step-linked.png: the signature inside an
#: IDAT chunk's compressed data).
CHANCE = bytes(range(256)) * 3 + b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\xff" * 8 + bytes(64)
REAL_GZIP = gzip.compress(b'{"records": []}')
#: Confirmation fix (C-001-3), 2026-11-16: a member that decodes its content and is rejected only
#: afterwards (a wrong trailer CRC, a wrong size, one corrupted byte in the deflate data) is still
#: an archive. Long enough that the rejection comes after the first piece the check feeds the
#: decoder.
LONG_GZIP = gzip.compress(
    "\n".join(f"record {i}: private answer text {i * 7919 % 1000}" for i in range(60)).encode(),
    mtime=0,
)


def _corrupt(member: bytes, at: int, flip: int) -> bytes:
    return member[:at] + bytes([member[at] ^ flip]) + member[at + 1 :]


CORRUPTED_GZIP = {
    "gzip-wrong-crc-in-image": _corrupt(LONG_GZIP, len(LONG_GZIP) - 8, 0xFF),
    "gzip-wrong-size-in-image": _corrupt(LONG_GZIP, len(LONG_GZIP) - 1, 0x01),
    "gzip-flipped-byte-in-image": _corrupt(LONG_GZIP, len(LONG_GZIP) // 2, 0x55),
}


def _broken_crc(png: bytes) -> bytes:
    at = png.index(b"IEND") + 4
    return png[:at] + bytes([png[at] ^ 0xFF]) + png[at + 1 :]


def _escape_all(text: str, fmt: str) -> str:
    return "".join(fmt.format(ord(c)) for c in text)


#: Every shape that must REFUSE the publish: path -> content. Built at run time.
REFUSED: dict[str, str | bytes] = {
    # Round 1's shapes (OR1-001-3).
    "tests/fixtures/stray_recording.json": CASSETTE,
    "tests/fixtures/escaped.json": '{"format": "' + MARK.replace("/", "\\/") + '"}',
    "tests/fixtures/pretty.json": '{\n  "format":\n    "' + MARK + '",\n  "records": []\n}',
    "tests/fixtures/udot.json": '{"format": "' + MARK.replace(".", "\\u002e") + '"}',
    "tests/fixtures/ukey.json": '{"\\u0066ormat": "' + MARK + '"}',
    "tests/fixtures/run.jsonl": '{"format": "' + MARK + '"}\n{"seq": 0}\n',
    "tests/fixtures/recording.yaml": "format: " + MARK + "\nrecords: []\n",
    "eval/recorded.yml": "format: '" + MARK + "'\n",
    # Names (any case) outside a cassettes directory: refused, not stripped.
    "tests/harness/misplaced.cassette.json": "{}",
    "tests/fixtures/x.cassette.jsonl": "{}",
    "tests/fixtures/y.cassette.yaml": "{}",
    "tests/fixtures/x.Cassette.json": "{}",
    # Round 2's shapes (OR2-001-5): encodings and escapings of the format's name.
    "tests/fixtures/url-encoded.txt": urllib.parse.quote(CASSETTE, safe=""),
    "tests/fixtures/double-url-encoded.txt": urllib.parse.quote(
        urllib.parse.quote(CASSETTE, safe=""), safe=""
    ),
    "tests/fixtures/form-encoded.txt": urllib.parse.urlencode({"cassette": CASSETTE}),
    "tests/fixtures/base64.txt": base64.b64encode(CASSETTE.encode()).decode(),
    "tests/fixtures/base64-offset.txt": base64.b64encode(b"xy" + CASSETTE.encode()).decode(),
    "tests/fixtures/base64-urlsafe.txt": base64.urlsafe_b64encode(
        b"x" + CASSETTE.encode()
    ).decode(),
    "tests/fixtures/base64-wrapped.txt": "\n".join(
        base64.b64encode(CASSETTE.encode()).decode()[i : i + 8] for i in range(0, 120, 8)
    ),
    "tests/fixtures/hex.txt": CASSETTE.encode().hex(),
    "tests/fixtures/utf16.json": CASSETTE.encode("utf-16"),
    "tests/fixtures/utf16be.json": CASSETTE.encode("utf-16-be"),
    "tests/fixtures/utf32.json": CASSETTE.encode("utf-32"),
    "tests/fixtures/html-entity.html": CASSETTE.replace('"', "&quot;"),
    "tests/fixtures/html-numeric.html": _escape_all(MARK, "&#{};"),
    "tests/fixtures/html-hex.html": _escape_all(MARK, "&#x{:x};"),
    "tests/fixtures/python-x.txt": _escape_all(MARK, "\\x{:02x}"),
    "tests/fixtures/octal.txt": _escape_all(MARK, "\\{:03o}"),
    "tests/fixtures/quoted-printable.txt": "format: " + _escape_all(MARK, "={:02X}"),
    "tests/fixtures/upper.json": '{"FORMAT": "' + MARK.upper() + '"}',
    "tests/fixtures/yaml-tag.yaml": "format: !!str " + MARK + "\n",
    "tests/fixtures/yaml-folded.yaml": "format: >-\n  " + MARK + "\n",
    "tests/fixtures/yaml-literal.yaml": "format: |\n  " + MARK + "\n",
    "tests/fixtures/yaml-split.yaml": "format: >-\n  " + MARK[:8] + "\n  " + MARK[8:] + "\n",
    "tests/fixtures/yaml-double-quoted-escape.yaml": 'format: "' + MARK.replace(".", "\\x2e") + '"',
    "tests/fixtures/toml.toml": 'format = "' + MARK + '"\n',
    "tests/fixtures/notebook.ipynb": json.dumps({"cells": [{"source": [CASSETTE]}]}),
    "manual/docs/example.md": "An example:\n\n```json\n" + CASSETTE + "\n```\n",
    # Records with NO format key that carry the cassette fields.
    "tests/fixtures/no-marker-records.json": json.dumps({"records": [RECORD]}),
    "tests/fixtures/no-marker-record.jsonl": json.dumps(RECORD) + "\n" + json.dumps(RECORD) + "\n",
    "tests/fixtures/no-marker-records.yaml": yaml.safe_dump({"records": [RECORD]}),
    "tests/fixtures/no-marker-flow.yaml": yaml.safe_dump(
        {"records": [RECORD]}, default_flow_style=True
    ),
    "tests/fixtures/no-marker-upper.json": json.dumps({"Request": {"path": "/"}, "ANSWER": {}}),
    "tests/fixtures/no-marker-url-encoded.txt": urllib.parse.quote(json.dumps(RECORD), safe=""),
    "tests/fixtures/no-marker-in-notebook.ipynb": json.dumps(
        {"cells": [{"source": [json.dumps({"records": [RECORD]})]}]}
    ),
    # Compressed and archived, whatever the name or trailing/leading bytes.
    "tests/fixtures/old/run.json.gz": gzip.compress(CASSETTE.encode()),
    "tests/fixtures/gzip-trailing.gz": gzip.compress(CASSETTE.encode()) + b"GARBAGE",
    "tests/fixtures/gzip-renamed.json": gzip.compress(CASSETTE.encode()) + b"GARBAGE",
    "tests/fixtures/gzip-leading.bin": b"HEADER" + gzip.compress(b"{}"),
    "tests/fixtures/gzip-of-gzip.gz": gzip.compress(gzip.compress(CASSETTE.encode())),
    "tests/fixtures/zip.zip": _zip("run.json", CASSETTE),
    "tests/fixtures/zip-renamed.dat": _zip("run.json", "{}"),
    "tests/fixtures/zip-appended.svg": b"<svg/>" + _zip("run.json", "{}"),
    "tests/fixtures/bz2.json.bz2": bz2.compress(CASSETTE.encode()),
    "tests/fixtures/bz2-renamed.txt": bz2.compress(b"{}") + b"TRAILING",
    "tests/fixtures/xz.json.xz": lzma.compress(CASSETTE.encode()),
    "tests/fixtures/xz-renamed.txt": lzma.compress(b"{}") + b"TRAILING",
    "tests/fixtures/tar-renamed.txt": _tar("run.json", "{}"),
    "tests/fixtures/empty.zip": b"",
    # R3 review fix (OR3-001-7): a PNG is checked like any file outside its image data, and a gzip
    # member inside its image data is still an archive.
    "manual/static/img/gzip-in-image.png": _png(CHANCE + REAL_GZIP + bytes(32)),
    "manual/static/img/gzip-after-iend.png": _png(CHANCE, after=REAL_GZIP),
    "manual/static/img/gzip-in-a-chunk.png": _png(CHANCE, _chunk(b"prVt", REAL_GZIP)),
    "manual/static/img/zip-in-image.png": _png(CHANCE + b"PK\x03\x04" + bytes(32)),
    "manual/static/img/bad-crc.png": _broken_crc(_png(CHANCE)),
    "manual/static/img/not-a-png.png": b"\x89PNG\r\n\x1a\n" + CHANCE,
    # Confirmation fix (C-001-3): a corrupted member inside the image data is still an archive.
    **{
        f"manual/static/img/{name}.png": _png(CHANCE + member + bytes(32))
        for name, member in CORRUPTED_GZIP.items()
    },
}
#: Refused because the file cannot be checked; planted specially.
OVERSIZE = "tests/fixtures/big.json"
UNREADABLE = "tests/fixtures/unreadable.json"

#: Cassette trees: removed by the strip, whatever the letter case or what they hold.
CASSETTE_TREES = {
    "tests/fixtures/cassettes/private/miserver/models.list.cassette.json": CASSETTE,
    "tests/fixtures/cassettes/private/eval/run-1.cassette.json": CASSETTE,
    # Neither named nor shaped like a cassette: only the tree's removal takes it.
    "tests/fixtures/cassettes/private/eval/recording-notes.txt": "fixture run notes\n",
    "tests/fixtures/cassettes/drafts/no_format.json": "{}",
    "tests/fixtures/cassettes/README.md": "# the cassette root\n",
    "eval/cassettes/run-2/notes.txt": "{}",
    "eval/Cassettes/upper.json": CASSETTE,
    "tests/CASSETTES/x.json": json.dumps({"records": [RECORD]}),
}
PLANTED_REMOVED = {
    "docs/reviews/round1.md": "# a review record\n",
    "docs/notes.md": "# private notes\n",
    "0xcc/tasks/x.md": "# tasks\n",
    "AGENT.md": "# agent\n",
    "CLAUDE.md": "@AGENT.md\n",
    "scripts/private/record.sh": "#!/bin/sh\n",
}
KEPT: dict[str, str | bytes] = {
    "docs/schemas/x.json": json.dumps({"$id": "x"}),
    "docs/schemas/README.md": "# Schemas\n",
    "docs/REUSE.md": "# Reuse\n",
    "README.md": "# miAssist\n",
    "scripts/write_contracts.py": "print('ok')\n",
    # Code naming a request and an answer is not record data.
    "scripts/recorder.py": 'record = {"request": req, "answer": ans}\n',
    "src/example/model.py": "class Record:\n    request: Request\n    answer: Answer\n",
    "manual/docs/faq.md": "Ask a question; the answer comes back.\nrequest: see below\n",
    "manual/static/img/logo.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
    "manual/static/img/logo.png": b"\x89PNG\r\n\x1a\n" + bytes(range(256)),
    # R3 review fix (OR3-001-7): a real image whose compressed data carries the gzip signature by
    # chance is published (it was refused before), stored and compressed.
    "manual/static/img/screenshot.png": _png(CHANCE),
    "manual/static/img/screenshot-deflated.png": _png(CHANCE * 50, level=9),
    "tests/fixtures/plain.json": json.dumps({"request_id": "r1", "answers": [1, 2]}),
}


def strip_script() -> str:
    doc: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        s
        for s in doc["jobs"]["sync"]["steps"]
        if s.get("name") == "Remove excluded files and folders"
    )
    script: str = step["run"]
    return script


def verify_script() -> str:
    doc: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        s for s in doc["jobs"]["sync"]["steps"] if s.get("name") == "Verify the published mirror"
    )
    script: str = step["run"]
    return script


def write(root: Path, files: dict[str, str] | dict[str, str | bytes]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)


def plant(root: Path) -> None:
    write(root, {**CASSETTE_TREES, **PLANTED_REMOVED, **KEPT})
    (root / ".github/scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, root / ".github/scripts/cassette_strip.py")


def plant_one(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if name == OVERSIZE:
        with path.open("wb") as fh:
            fh.write(b"{}")
            fh.truncate(STRIP.MAX_BYTES + 1)  # sparse: cheap to plant
    elif name == UNREADABLE:
        path.write_text("{}")
        path.chmod(0)
    else:
        write(root, {name: REFUSED[name]})
    return path


def run_strip_step(root: Path) -> subprocess.CompletedProcess[str]:
    script = strip_script().replace("python3 ", sys.executable + " ")
    return subprocess.run(
        ["bash", "-c", script], cwd=root, capture_output=True, text=True, check=False
    )


def check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--check", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_scan_finds_the_planted_cassette_root(tmp_path: Path) -> None:
    plant(tmp_path)
    assert by_path(tmp_path) >= {
        Path(n) for n in CASSETTE_TREES if n.startswith("tests/fixtures/cassettes/private/")
    }


def test_strip_removes_every_cassette_tree_and_keeps_public_files(tmp_path: Path) -> None:
    plant(tmp_path)
    result = run_strip_step(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all_cassettes(tmp_path) == set(), "a cassette survived the mirror strip"
    survivors = [n for n in {**CASSETTE_TREES, **PLANTED_REMOVED} if (tmp_path / n).exists()]
    assert not survivors, f"excluded paths survived the strip: {survivors}"
    assert not any(p.name.lower() == "cassettes" for p in tmp_path.rglob("*"))
    missing = [n for n in KEPT if not (tmp_path / n).is_file()]
    assert not missing, f"public files were stripped: {missing}"


ALL_REFUSED = sorted([*REFUSED, OVERSIZE, UNREADABLE])


@pytest.mark.parametrize("name", ALL_REFUSED)
def test_strip_step_refuses_the_publish(tmp_path: Path, name: str) -> None:
    """Each shape alone stops the strip step (set -e: no snapshot, no push) and is named; the same
    tree without it publishes (the control)."""
    if name == UNREADABLE and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    plant(tmp_path)
    path = plant_one(tmp_path, name)
    result = run_strip_step(tmp_path)
    assert result.returncode != 0, f"{name} did not refuse the publish"
    assert f"REFUSED - {name}:" in result.stdout, result.stdout
    assert path.exists(), "a refused file must be left for the operator, not stripped"
    path.chmod(0o644)
    path.unlink()
    assert run_strip_step(tmp_path).returncode == 0


@pytest.mark.parametrize("name", ALL_REFUSED)
def test_verify_refuses_every_shape(tmp_path: Path, name: str) -> None:
    """The post-publish verify uses the same matcher: each shape alone makes it fail."""
    if name == UNREADABLE and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    plant_one(tmp_path, name)
    result = check(tmp_path)
    assert result.returncode == 1, (name, result.stdout, result.stderr)
    assert f"REFUSED - {name}:" in result.stdout


def test_format_name_allow_list_is_exact(tmp_path: Path) -> None:
    """A file listed in MAY_NAME_THE_FORMAT may name the format exactly its count of times."""
    path = tmp_path / "src/defines.py"
    path.parent.mkdir(parents=True)
    path.write_text('FORMAT = "' + MARK + '"\n')
    saved = dict(STRIP.MAY_NAME_THE_FORMAT)
    try:
        assert "names the cassette format" in STRIP.refusal(path, tmp_path)
        STRIP.MAY_NAME_THE_FORMAT["src/defines.py"] = 1
        assert STRIP.refusal(path, tmp_path) is None
        path.write_text('FORMAT = "' + MARK + '"\n' + CASSETTE + "\n")
        assert "2 times, 1 allowed" in STRIP.refusal(path, tmp_path)
    finally:
        STRIP.MAY_NAME_THE_FORMAT.clear()
        STRIP.MAY_NAME_THE_FORMAT.update(saved)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [n for n in out.split("\0") if n and (REPO_ROOT / n).is_file()]


#: What the strip step may remove from the real tree, and nothing else.
EXCLUDED_PREFIXES = ("0xcc/", ".claude/", "backups/", "scripts/private/")
EXCLUDED_FILES = {"CLAUDE.md", "AGENT.md", "GEMINI.md"}


def excluded(name: str) -> bool:
    parts = name.split("/")
    if name in EXCLUDED_FILES or name.startswith(EXCLUDED_PREFIXES):
        return True
    if any(p.lower() == "cassettes" for p in parts[:-1]):
        return True
    return parts[0] == "docs" and parts[1] not in ("schemas", "REUSE.md")


def test_this_checkout_publishes_and_loses_no_legitimate_file(tmp_path: Path) -> None:
    """Over-strip guard (OR2-001-5): this checkout's tracked tree passes the strip step, and every
    tracked file outside the excluded paths is still there afterwards (e.g. a test that mentions
    the format is neither stripped nor refused)."""
    names = tracked_files()
    assert "tests/unit/test_mirror_strip.py" in names
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, target)
    result = run_strip_step(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    lost = [n for n in names if not excluded(n) and not (tmp_path / n).is_file()]
    assert not lost, f"published files were stripped: {lost}"


def make_mirror(root: Path, files: dict[str, str | bytes], sha: str) -> Path:
    mirror = root / "mirror"
    mirror.mkdir()
    write(
        mirror,
        {
            "README.md": "# miAssist\n",
            "LICENSE": "MIT\n",
            "manual/docusaurus.config.ts": "export default {};\n",
            "manual/package-lock.json": "{}\n",
            "docs/schemas/README.md": "# Schemas\n",
            "docs/REUSE.md": "# Reuse\n",
            **files,
        },
    )
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        [
            "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m",
            f"snapshot\n\nSource-Commit: {sha}\nPrivate-CI: passed",
        ],
    ):  # fmt: skip
        subprocess.run(["git", *args], cwd=mirror, check=True, env=env, capture_output=True)
    return mirror


def run_verify_step(
    tmp_path: Path, files: dict[str, str | bytes]
) -> subprocess.CompletedProcess[str]:
    sha = "0123456789abcdef0123456789abcdef01234567"
    mirror = make_mirror(tmp_path, files, sha)
    verify_dir = tmp_path / "verify"
    script = verify_script()
    swaps = {
        'git clone --quiet "$REMOTE" /tmp/verify': f'git clone --quiet "{mirror}" "{verify_dir}"',
        "rm -rf /tmp/verify": f'rm -rf "{verify_dir}"',
        "cd /tmp/verify": f'cd "{verify_dir}"',
        "${{ needs.gate.outputs.sha }}": sha,
        "python3 ": sys.executable + " -I ",
    }
    for old, new in swaps.items():
        assert old in script, f"the verify step changed shape: {old!r} is gone"
        script = script.replace(old, new)
    assert "/tmp/verify" not in script
    env = {
        **os.environ,
        "GITHUB_WORKSPACE": str(REPO_ROOT),
        "SYNC_TOKEN": "",  # the clone is local; the token is never read
        "MIRROR": "example/mirror",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, env=env, check=False
    )


def test_verify_step_passes_a_clean_mirror(tmp_path: Path) -> None:
    """The control for the next test: the harness itself does not fail the verify."""
    result = run_verify_step(tmp_path, {})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Mirror verified" in result.stdout


@pytest.mark.parametrize(
    "name",
    ["tests/fixtures/stray_recording.json", "tests/fixtures/zip-renamed.dat", "x/Cassettes/a.txt"],
)
def test_verify_step_fails_on_a_published_leak(tmp_path: Path, name: str) -> None:
    """R2 review fix OR2-001-5 (M-14): the verify step's cassette check sets FAILED and the step
    exits non-zero; pinned by running the step, not by reading its text."""
    content = REFUSED.get(name, "{}")
    result = run_verify_step(tmp_path, {name: content})
    assert result.returncode != 0, result.stdout
    assert f"REFUSED - {name}:" in result.stdout
    assert "LEAK - a cassette" in result.stdout
    assert "mirror verification FAILED" in result.stdout


def test_this_file_and_the_script_pass_their_own_check(tmp_path: Path) -> None:
    """Both are published: neither names the format nor carries records."""
    for source in (Path(__file__), SCRIPT, REPO_ROOT / "tests/support/cassette_scan.py"):
        copy = tmp_path / source.name
        shutil.copy(source, copy)
        assert STRIP.refusal(copy, tmp_path) is None, source
    assert CASSETTE_FORMAT == MARK


def test_a_chance_gzip_signature_in_image_data_is_not_an_archive() -> None:
    """R3 review fix (OR3-001-7), 2026-11-16: why the screenshot passes and the planted PNGs do not
    (the control is the same image with a real member, or the signature outside the image data)."""
    shot = KEPT["manual/static/img/screenshot.png"]
    assert isinstance(shot, bytes) and STRIP._GZIP in shot
    assert not STRIP.is_archive(Path("x.png"), shot)
    assert STRIP.is_archive(Path("x.png"), b"x" + shot), "outside a PNG, the signature refuses"
    for name in (
        "gzip-in-image",
        "gzip-after-iend",
        "gzip-in-a-chunk",
        "zip-in-image",
        "bad-crc",
        "not-a-png",
        *CORRUPTED_GZIP,
    ):
        data = REFUSED[f"manual/static/img/{name}.png"]
        assert isinstance(data, bytes)
        assert STRIP.is_archive(Path("x.png"), data), name
    assert STRIP._gzip_member_at(REAL_GZIP, 0)
    assert STRIP._gzip_member_at(REAL_GZIP[:12], 0), "a truncated member is an archive"
    assert not STRIP._gzip_member_at(CHANCE, CHANCE.index(STRIP._GZIP))


@pytest.mark.parametrize("name", sorted(CORRUPTED_GZIP))
def test_a_corrupted_gzip_member_is_still_an_archive(name: str) -> None:
    """Confirmation fix (C-001-3), 2026-11-16: each planted member is rejected by the decoder (so
    the R3 rule alone published it) after decoding its content, and the check refuses it."""
    member = CORRUPTED_GZIP[name]
    with pytest.raises((OSError, EOFError, zlib.error)):
        gzip.decompress(member)
    decoder = zlib.decompressobj(31)
    with pytest.raises(zlib.error):
        decoder.decompress(member[:64]) + decoder.decompress(member[64:])
    assert STRIP._gzip_member_at(member, 0), name
    assert STRIP._gzip_member_at(CHANCE + member, len(CHANCE)), name
