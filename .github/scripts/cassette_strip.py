"""Strip the cassette tree from a tree about to be published, then REFUSE to publish anything that
still looks like a cassette (A22; Foundation 3.7; R1 review fix OR1-001-3; R2 review fix OR2-001-5,
2026-11-16: fail closed).

    python .github/scripts/cassette_strip.py --strip [ROOT]   # remove cassette trees, then check
    python .github/scripts/cassette_strip.py --check [ROOT]   # exit 1 naming every refused file

ONE matcher for both the mirror strip and its post-publish verify, so the backstop can never be
weaker than the strip.

The strip removes exactly one thing: every directory named ``cassettes`` in any letter case
(``tests/fixtures/cassettes/`` is the one cassette root). It removes nothing else. Every remaining
file is then checked, and the run REFUSES (exit 1, nothing is published) when any file:

- lies under a ``cassettes`` directory, or has a ``.cassette.`` part in its name (any case);
- cannot be read, or is larger than ``MAX_BYTES``;
- is compressed or archived: gzip, zip, bzip2, xz, zstd, 7z or tar, by name or by the format's
  signature anywhere in the file (so trailing or leading bytes do not hide it); inside a
  well-formed PNG's image data only, a gzip signature counts when a gzip member follows it, since
  deflate output carries the 3-byte signature by chance (R3 review fix OR3-001-7), and a member
  that decodes anything before it is rejected (a wrong trailer, a corrupted byte) still counts
  (confirmation fix C-001-3);
- names the cassette format in any encoding or escaping: UTF-8/16/32, JSON, YAML, Python and
  octal escapes, URL and form encoding, HTML entities, quoted-printable, base64 and hex, with
  whitespace (YAML block and folded scalars, wrapped lines) removed and letter case ignored;
- carries a cassette record without the format key: a mapping (or YAML-style key lines) holding
  both a ``request`` and an ``answer``.

A file the cassette format itself is defined in may name the format, but only the exact number of
times listed in ``MAY_NAME_THE_FORMAT``, and is checked for everything else; the generated schema
may also describe a record's fields (``MAY_DESCRIBE_RECORDS``, exact paths). To publish a new such
file, add it there with its count; that is a reviewed change to this script.

This file never spells the format out, so it passes its own check. Leak tests must look for the
encoded form (suite memory ``leak-tests-must-look-for-the-encoded-form``):
``tests/unit/test_mirror_strip.py`` plants each shape and runs both modes and both workflow steps.
"""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import struct
import sys
import urllib.parse
import zlib
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
#: The two words of the format's name, reversed so this source does not carry them.
_WORDS = ("tsissaim"[::-1], "ettessac"[::-1])
MARK = _WORDS[0] + "." + _WORDS[1]
#: The name in normalised text: the two words with at most three separator characters between.
_NAMED = re.compile(_WORDS[0] + r"[^a-z0-9]{0,3}" + _WORDS[1])

#: Published files that define the format and so must name it; value = the exact count allowed.
MAY_NAME_THE_FORMAT: dict[str, int] = {
    "tests/support/cassette.py": 6,  # the format's model: FORMAT, the Literal, docstrings
    # The generated schema (its $id and const); the name is built so this file does not spell it.
    "tests/fixtures/" + _WORDS[0] + "-" + _WORDS[1] + "-v1.schema.json": 2,
    # 002 Evaluation (integration OVN-miassist-int-2, counted on the rebased tree; OR3-001-8): the
    # eval package's cassette writer, its result schemas, its example environment and two tests.
    "eval/miassist_eval/cassette.py": 2,
    "eval/miassist_eval/schemas.py": 2,
    "eval/.env.example": 1,
    "eval/tests/unit/test_cassette_format_is_core.py": 1,
    "eval/tests/unit/test_mirror_strip.py": 3,
}
#: Published files that describe a record's fields (and so hold ``request`` and ``answer`` keys)
#: without being one: exact paths. The schema is pinned to the model by ``test_cassette_root``.
MAY_DESCRIBE_RECORDS: frozenset[str] = frozenset(
    {"tests/fixtures/" + _WORDS[0] + "-" + _WORDS[1] + "-v1.schema.json"}
)

#: Names (lower case) of compressed or archived files, refused whatever their content.
_ARCHIVE_SUFFIXES = (
    ".gz", ".tgz", ".zip", ".bz2", ".tbz", ".tbz2", ".xz", ".txz", ".zst", ".7z", ".tar", ".lz",
    ".lzma", ".lz4", ".z", ".jar", ".whl", ".egg",
)  # fmt: skip
#: Format signatures, refused anywhere in a file.
_SIGNATURES = (
    b"\x1f\x8b\x08",  # gzip (deflate)
    b"PK\x03\x04",  # zip local file header
    b"PK\x05\x06",  # zip end of central directory (a zip appended to another file)
    b"PK\x07\x08",  # zip spanned
    b"\xfd7zXZ\x00",  # xz
    b"\x28\xb5\x2f\xfd",  # zstd
    b"7z\xbc\xaf\x27\x1c",  # 7z
    b"ustar\x00",  # POSIX tar
    b"ustar  \x00",  # GNU tar
)
_BZIP2 = re.compile(rb"BZh[1-9]1AY&SY")

_JSON_U = re.compile(r"\\u([0-9a-fA-F]{4})")
_JSON_U8 = re.compile(r"\\U([0-9a-fA-F]{8})")
_X = re.compile(r"\\x([0-9a-fA-F]{2})")
_OCTAL = re.compile(r"\\([0-7]{3})")
_PCT_U = re.compile(r"%u([0-9a-fA-F]{4})")
_QP = re.compile(r"=([0-9A-F]{2})")
_SPACE = re.compile(r"\s+")
#: A record key written as YAML (block or flow), TOML or similar text: ``request:``,
#: ``- "answer" =``, ``{request: {...}, answer: ...}``.
_KEY_LINE = r"""(?m)(?:^|[\s\-{,\[])["']?{key}["']?\s*[:=]"""
_REQUEST_LINE = re.compile(_KEY_LINE.replace("{key}", "request"), re.IGNORECASE)
_ANSWER_LINE = re.compile(_KEY_LINE.replace("{key}", "answer"), re.IGNORECASE)


def _chr(code: int) -> str:
    try:
        return chr(code)
    except (ValueError, OverflowError):
        return ""


def _unescape_once(text: str) -> str:
    text = _JSON_U8.sub(lambda m: _chr(int(m.group(1), 16)), text)
    text = _JSON_U.sub(lambda m: _chr(int(m.group(1), 16)), text)
    text = _X.sub(lambda m: _chr(int(m.group(1), 16)), text)
    text = _OCTAL.sub(lambda m: _chr(int(m.group(1), 8)), text)
    text = _PCT_U.sub(lambda m: _chr(int(m.group(1), 16)), text)
    text = urllib.parse.unquote_plus(text)
    text = _QP.sub(lambda m: _chr(int(m.group(1), 16)), text)
    text = html.unescape(text)
    return text.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")


def normalise(text: str) -> str:
    """Undo every escaping above, three times over (nested escapes), drop whitespace, lower-case."""
    for _ in range(3):
        text = _unescape_once(text)
    return _SPACE.sub("", text).lower()


def _decodings(data: bytes) -> list[str]:
    """The bytes read as UTF-8 and, at both alignments, as UTF-16 and UTF-32 in both orders."""
    texts = [data.decode("utf-8", errors="replace")]
    if b"\x00" in data:
        for shift in range(4):
            for codec in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                texts.append(data[shift:].decode(codec, errors="ignore"))
    return texts


def _encoded_marks() -> list[str]:
    """The format's name as base64 (standard and URL-safe, at the three alignments) and as hex."""
    out = [MARK.encode().hex()]
    raw = MARK.encode()
    for shift in range(3):
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            encoded = encode(b"\x00" * shift + raw).decode().rstrip("=")
            # Drop the characters that mix pad bytes in, and the last one, which mixes what follows.
            start = (shift * 4 + 2) // 3
            out.append(encoded[start:-1])
    return out


_ENCODED = _encoded_marks()


def name_count(data: bytes) -> int:
    """How many times the format is named, in the decoding that names it most."""
    best = 0
    for text in _decodings(data):
        count = len(_NAMED.findall(normalise(text)))
        compact = _SPACE.sub("", text)
        count += compact.lower().count(_ENCODED[0])
        count += sum(compact.count(e) for e in _ENCODED[1:])
        best = max(best, count)
    return best


def _walk(value: object) -> bool:
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value}
        if {"request", "answer"} <= keys:
            return True
        return any(_walk(v) for v in value.values())
    if isinstance(value, list):
        return any(_walk(v) for v in value)
    if isinstance(value, str) and len(value) > 16:
        return _record_text(value) or _record_json(value)
    return False


def _record_json(text: str) -> bool:
    candidates = [text, *text.splitlines()]
    for chunk in candidates:
        chunk = chunk.strip()
        if not chunk or chunk[0] not in "[{":
            continue
        try:
            if _walk(json.loads(chunk)):
                return True
        except (ValueError, RecursionError):
            continue
    return False


def _record_text(text: str) -> bool:
    return bool(_REQUEST_LINE.search(text) and _ANSWER_LINE.search(text))


#: Source code is not record data: a recorder or a cassette model names ``request`` and ``answer``
#: as fields. Its format name and archives are still checked.
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".css", ".sh")


def carries_records(path: Path, data: bytes) -> bool:
    if path.name.lower().endswith(_CODE_SUFFIXES):
        return False
    for text in _decodings(data):
        for candidate in (text, normalise_keep_space(text)):
            if _record_json(candidate) or _record_text(candidate):
                return True
    return False


def normalise_keep_space(text: str) -> str:
    for _ in range(3):
        text = _unescape_once(text)
    return text


def _signed(data: bytes) -> bool:
    return any(sig in data for sig in _SIGNATURES) or bool(_BZIP2.search(data))


_PNG = b"\x89PNG\r\n\x1a\n"
_GZIP = _SIGNATURES[0]
#: The most a candidate gzip member is decompressed while being checked; past it, it is a member.
_GZIP_CHECK_BYTES = 256 * 1024 * 1024


def _png_parts(data: bytes) -> tuple[list[bytes], bytes] | None:
    """A well-formed PNG (every chunk's CRC correct, ending at IEND) split into the bytes outside
    its image data (each run checked like any file, including anything after IEND) and its image
    data (the IDAT payloads joined). ``None`` for anything else."""
    if not data.startswith(_PNG):
        return None
    outside: list[bytes] = []
    image: list[bytes] = []
    start = pos = len(_PNG)
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return None
        payload = data[pos + 8 : end - 4]
        if zlib.crc32(kind + payload) != struct.unpack(">I", data[end - 4 : end])[0]:
            return None
        if kind == b"IDAT":
            outside.append(data[start : pos + 8])
            image.append(payload)
            start = end - 4
        pos = end
        if kind == b"IEND":
            outside.append(data[start:])
            return outside, b"".join(image)
    return None


def _gzip_member_at(data: bytes, offset: int) -> bool:
    """Whether the bytes at ``offset`` are (or may be) a gzip member: True when they decode to the
    member's end, run out of data first (a truncated member), exceed the check's budget, or decode
    anything before the decoder rejects them; False only when the decoder rejects them before any
    output (a chance occurrence of the 3-byte signature).

    Confirmation fix (C-001-3), 2026-11-16: a member with a wrong trailer (CRC or size) or a
    corrupted byte decodes its content and is rejected only afterwards, and was published. The
    decoder is now fed in 64-byte pieces, so output decoded before a later rejection is counted;
    a chance signature is rejected within its first piece."""
    decoder = zlib.decompressobj(31)
    pending, seen = data[offset:], 0
    try:
        while pending and not decoder.eof:
            piece, pending = pending[:64], pending[64:]
            seen += len(decoder.decompress(piece, 1 << 20))
            pending = decoder.unconsumed_tail + pending
            if seen > _GZIP_CHECK_BYTES:
                return True
    except zlib.error:
        return seen > 0
    return True


def is_archive(path: Path, data: bytes) -> bool:
    if path.name.lower().endswith(_ARCHIVE_SUFFIXES):
        return True
    png = _png_parts(data)
    if png is None:
        return _signed(data)
    # R3 review fix (OR3-001-7), 2026-11-16: a PNG's image data is deflate output, where the
    # 3-byte gzip signature occurs by chance (about 6% per MB; 1 of 239 real images was refused).
    # In a well-formed PNG's image data, a gzip signature counts only when the bytes after it
    # decode as a gzip member (or run out first); every other signature, and every byte outside
    # the image data, is checked exactly as in any other file.
    outside, image = png
    if any(_signed(part) for part in outside):
        return True
    if any(sig in image for sig in _SIGNATURES[1:]) or _BZIP2.search(image):
        return True
    at = image.find(_GZIP)
    while at >= 0:
        if _gzip_member_at(image, at):
            return True
        at = image.find(_GZIP, at + 1)
    return False


def in_cassettes(rel: Path) -> bool:
    return any(part.lower() == "cassettes" for part in rel.parts[:-1])


def refusal(path: Path, root: Path) -> str | None:
    """Why this published file is refused, or None when it may be published."""
    rel = path.relative_to(root)
    if in_cassettes(rel):
        return "it lies under a cassettes directory"
    if ".cassette." in path.name.lower():
        return "its name marks it as a cassette"
    try:
        if path.stat().st_size > MAX_BYTES:
            return f"it is larger than {MAX_BYTES} bytes and cannot be checked"
        data = path.read_bytes()
    except OSError as exc:
        return f"it cannot be read ({type(exc).__name__})"
    if is_archive(path, data):
        return "it is compressed or archived and cannot be checked"
    allowed = MAY_NAME_THE_FORMAT.get(rel.as_posix(), 0)
    named = name_count(data)
    if named > allowed:
        return f"it names the cassette format ({named} times, {allowed} allowed)"
    if rel.as_posix() not in MAY_DESCRIBE_RECORDS and carries_records(path, data):
        return "it carries recorded request/answer records"
    return None


def published_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] == ".git" or path.is_symlink() or not path.is_file():
            continue
        files.append(path)
    return files


def find(root: Path) -> list[tuple[Path, str]]:
    found = []
    for path in published_files(root):
        reason = refusal(path, root)
        if reason is not None:
            found.append((path, reason))
    return found


def strip(root: Path) -> list[Path]:
    """Remove every directory named ``cassettes`` (any case); nothing else."""
    removed = []
    for folder in sorted(root.rglob("*"), key=lambda p: len(p.parts)):
        rel = folder.relative_to(root)
        if rel.parts[0] == ".git" or folder.is_symlink() or not folder.is_dir():
            continue
        if folder.name.lower() == "cassettes" and folder.exists():
            shutil.rmtree(folder)
            removed.append(folder)
    return removed


def report(root: Path) -> int:
    refused = find(root)
    for path, reason in refused:
        where = path.relative_to(root)
        print(f"::error::REFUSED - {where}: {reason} (A22; nothing is published)")
    return 1 if refused else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    if mode == "--strip":
        for folder in strip(root):
            print(f"stripped cassette tree: {folder.relative_to(root)}")
        return report(root)
    if mode == "--check":
        return report(root)
    print("usage: cassette_strip.py --strip|--check [ROOT]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
