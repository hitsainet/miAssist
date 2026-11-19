"""The secret scan over cassettes (FR-002.14; FTASKS 4.5): raw and base64 forms (suite memory
``leak-tests-must-look-for-the-encoded-form``). Used by the test over every take and by
``eval/scripts/scan_cassettes.py`` as a pre-commit hook."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from pathlib import Path

PATTERNS = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "hf_token": re.compile(r"hf_[A-Za-z0-9]{30,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password_field": re.compile(
        r'(?i)"(password|passwd|secret|api_key|access_token|token)"\s*:\s*"[^"]{6,}"'
    ),
}
#: Standard and URL-safe alphabets (R1 review fix OR1-002-7: base64url was found, but a key at a
#: non-aligned offset, e.g. ``"abc" + b64``, was missed; every alignment is now tried).
_B64 = re.compile(rb"[A-Za-z0-9+/_-]{24,}={0,2}")
_UNICODE = re.compile(r"\\+u([0-9a-fA-F]{4})")
_SLASH = re.compile(r"\\+/")


def unescape(text: str) -> str:
    """JSON escapes undone at any depth of escaping: ``\\u002d``, ``\\\\u002d`` and ``\\/``."""
    text = _UNICODE.sub(lambda m: chr(int(m.group(1), 16)), text)
    return _SLASH.sub("/", text)


def scan_text(text: str, extra_values: Iterable[str] = ()) -> list[str]:
    found = []
    for candidate in {text, unescape(text)}:
        found += [name for name, pat in PATTERNS.items() if pat.search(candidate)]
        for value in extra_values:
            if value and value in candidate:
                found.append("listed value")
    return sorted(set(found))


def decodings(chunk: bytes) -> list[str]:
    """Every decoding of one base64 run at each of the four alignments, in both alphabets."""
    out = []
    run = chunk.rstrip(b"=").replace(b"-", b"+").replace(b"_", b"/")
    for offset in range(4):
        part = run[offset:]
        part = part[: len(part) - (len(part) % 4 == 1)]
        try:
            raw = base64.b64decode(part + b"=" * (-len(part) % 4), validate=True)
        except ValueError:
            continue
        out.append(raw.decode("utf-8", "replace"))
    return out


def scan_bytes(data: bytes, extra_values: Iterable[str] = ()) -> list[str]:
    values = list(extra_values)
    text = data.decode("utf-8", "replace")
    found = scan_text(text, values)
    for source in {data, unescape(text).encode("utf-8", "replace")}:
        for chunk in _B64.findall(source):
            for decoded in decodings(chunk):
                found += [f"base64:{f}" for f in scan_text(decoded, values)]
    encoded = [base64.b64encode(v.encode()) for v in values if v]
    found += ["base64:listed value" for e in encoded if e in data]
    return sorted(set(found))


def scan_tree(root: Path, extra_values: Iterable[str] = ()) -> dict[str, list[str]]:
    values = list(extra_values)
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        hits = scan_bytes(path.read_bytes(), values)
        if hits:
            out[str(path.relative_to(root))] = hits
    return out
