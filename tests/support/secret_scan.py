"""The committed-file secret scanner (Foundation task 1.7).

Used by ``tests/unit/test_no_secrets_tracked.py`` over the repository and, from feature 001, by the
cassette recorder before it writes a file. Values that are visibly placeholders or test-only
defaults are allowed; anything else that looks like a credential is a finding.

R2 review fix (OR2-001-1), 2026-11-16: a key-named assignment is judged on its WHOLE value, never
its first word. A quoted value runs to its closing quote; an unquoted value runs to the end of the
line (or to a double quote or backtick that closes an enclosing string); a YAML block indicator
(``|``, ``>-``...) means the value is the next non-blank line. The earlier rule that exempted an
English article after the colon is gone: it let ``PASSWORD="the horse battery staple"`` through.
Prose that genuinely follows a key word is allowed only by its exact text in ``KNOWN_BENIGN``.

R3 review fix (OR3-001-1), 2026-11-16: an unquoted value ends at a trailing `` #`` comment or
before the next ``key=`` / ``key:`` on the same line (the whole-value rule had let a comment word
or a placeholder-shaped first value hide a real value).
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

#: The key word of a credential assignment, written as code, env, YAML or JSON (the key may be
#: quoted, so ``"hf_token": "..."`` counts). ``api-key`` and ``ACCESS_KEY``: R3 review fix round.
#: Confirmation fix (C-001-2), 2026-11-16: ``apiKey``/``apikey``, ``accessKey`` and ``private_key``
#: (the separator is optional). ``Authorization`` is deliberately NOT a key word (fixtures name the
#: header); a bearer credential is caught by its shape instead.
_KEY = (
    r"""(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY))"""
    r"""\\?["']?\s*([:=])\s*"""
)

#: Shapes of real credentials.
SHAPES: dict[str, re.Pattern[str]] = {
    "github_token": re.compile(
        r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|github_pat_[A-Za-z0-9_]{40,}"
    ),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "anthropic_or_openai_key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{32,}\b"),
    "url_with_credentials": re.compile(r"[a-z][a-z0-9+.\-]*://([^\s:/@'\"]+):([^\s@/'\"]+)@"),
    "password_assignment": re.compile(_KEY),
    # Confirmation fix (C-001-2), 2026-11-16: an HTTP bearer credential in any text (a token-like
    # value: 16+ characters holding a digit), whatever key, header list or prose it sits in.
    "bearer_token": re.compile(
        r"(?i)\bbearer\s+((?=[A-Za-z0-9._~+/\-]*[0-9])[A-Za-z0-9._~+/\-]{16,}=*)"
    ),
}

#: A value matching any of these is a placeholder, a reference or a test-only default.
PLACEHOLDER = re.compile(r"""(?ix)^(
        \$\{?[A-Za-z_][A-Za-z0-9_]*\}?.*   # ${VAR} / $VAR
      | \$\(.*                              # $(command)
      | <[^>]*>                             # <placeholder>
      | \*+ | x+ | \.\.\.?                  # masked
      | .*test-only.* | .*example.* | .*changeme.* | .*placeholder.* | .*redacted.*
      | secretKeyRef | valueFrom | "" | '' | none | null | true | false | any | read | write
      | pullsecret:.*                       # a reference to a cluster pull secret
      | \{\{.* | \$\{\{.*                     # templating (Jinja, GitHub Actions)
      | .*…                                 # elided in prose
      | [A-Za-z_][A-Za-z0-9_.]*\(.*         # a call: os.environ.get(...)
      | [A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_].*  # an attribute reference: settings.password
      | str | bytes | Optional | None.*
    )$""")

#: Exact known-benign values, each scoped to the one tracked file it occurs in: (path, whole value).
#: A new entry is a reviewed change, never a pattern (R2 review fix OR2-001-1).
KNOWN_BENIGN: frozenset[tuple[str, str]] = frozenset(
    {
        # The miDataworks snapshot's Hub-search description (the false positive behind 49b0766).
        (
            "tests/fixtures/openapi/midataworks.json",
            "the operator's search uses\\nthe stored one, an agent's is anonymous (022, suite A17).",
        ),
        (
            "0xcc/prds/004_FPRD|Playbook_Dataset.md",
            "Q8); a large or unknown-size import (the operator's, Q9",
        ),
        ("0xcc/tids/002_FTID|Evaluation.md", "GitHub's own job token"),
        ("0xcc/tids/002_FTID|Evaluation.md", "image build login"),
        ("manual/package-lock.json", "^5.0.1"),  # the npm package "registry-auth-token"
        ("scripts/snapshot_openapi.py", "snapshot-import-only"),
        # 002 Evaluation (integration OVN-miassist-int-3): prose descriptions of the CI secrets the
        # eval guard allows, a variable passed through, and two test-only values.
        ("eval/miassist_eval/ci_guard.py", "GitHub's own job token"),
        ("eval/miassist_eval/ci_guard.py", "image build login"),
        ("eval/miassist_eval/sut.py", "token"),
        ("eval/tests/component/test_driver_claude_code.py", "k-value"),
        ("eval/tests/unit/test_secret_scan.py", "abcdef123456"),
        # 003 Detector Probe (integration OVN-miassist-int-3): prose about the agent download flag.
        (
            "0xcc/tasks/003_FTASKS|Playbook_Detector_Probe.md",
            "False found); FR-003.9a and Core's Hub rule are the only enforcement, so 3.2's controls"
            " are mandatory. Interim debt (A23): miDataworks' search runs on the stored token]*",
        ),
        # 004 Dataset (integration OVN-miassist-int-3): prose and one test-only value.
        (
            "0xcc/tasks/004_FTASKS|Playbook_Dataset.md",
            "False), commit eca7445 on mcpux/022-P1, not yet on miDataworks main. Interim debt"
            " recorded (stored-token search until 022-P1 lands); controls C-2.4 and"
            " C-3.1-skipcheck are red (0xcc/reviews/004_mutations.md).",
        ),
        ("src/miassist/guidance/tools.yaml", "a missing token is the operator's step."),
        ("tests/playbooks/dataset/test_find_build.py", "hf_evalfx"),
    }
)

_BLOCK = re.compile(r"^[|>][-+0-9]*\s*(#.*)?$")
#: Where an unquoted value ends early (OR3-001-1): a trailing comment, or the next key on the line.
#: Confirmation fix (C-001-1), 2026-11-16: the next key may follow a ``;`` or ``&`` with no space
#: (``TOKEN=$HOME;API_KEY=...``). The cut is only before a following key, so a ``;`` inside a value
#: (``PASSWORD=ab;cdefgh``) never shortens it.
_UNQUOTED_END = re.compile(
    r"""\s\#|(?:\s|;|&)(?=\\?["']?[A-Za-z_][\w\-]*\\?["']?\s*(?:=(?!=)|:(?:\s|$)))"""
)
_SPACE = re.compile(r"\s")
#: ``name: Type = value`` (a Python annotated assignment): the value is after the ``=``.
_ANNOTATED = re.compile(r"^[A-Za-z_][\w\[\], |.]*?\s*=\s*(?!=)")


def whole_value(rest: str, following: list[str], separator: str = "=") -> tuple[str, int]:
    """The whole value after ``key:`` / ``key=``, and how many characters of ``rest`` it spans:
    to the closing quote when quoted, the next non-blank line after a YAML block indicator, else
    to the end of the line (or a double quote or backtick closing an enclosing string)."""
    lead = len(rest) - len(rest.lstrip())
    body = rest[lead:]
    if separator == ":" and (annotated := _ANNOTATED.match(body)):
        value, span = whole_value(body[annotated.end() :], following)
        return value, lead + annotated.end() + span
    # A backtick-quoted single token (a JavaScript template string) is the value (confirmation
    # round, OVN-miassist-core-40). With whitespace inside it is a shell command substitution or
    # Markdown prose, and the value ends at the backtick as before.
    if body.startswith("`") and (end := body.find("`", 1)) > 0 and not _SPACE.search(body[1:end]):
        return body[1:end], lead + end + 1
    for quote in ('\\"', "\\'", '"', "'"):
        if body.startswith(quote):
            end = body.find(quote, len(quote))
            while end > 0 and len(quote) == 1 and body[end - 1] == "\\":
                end = body.find(quote, end + 1)
            if end < 0:
                return body[len(quote) :].strip(), len(rest)
            return body[len(quote) : end].strip(), lead + end + len(quote)
    if _BLOCK.match(body):
        for line in following:
            if line.strip():
                return line.strip(), len(rest)
        return "", len(rest)
    stops = [body.index(c) for c in ('"', "`") if c in body]
    # R3 review fix (OR3-001-1), 2026-11-16: an unquoted value also ends at a trailing comment
    # (whitespace then ``#``) and before the next ``key=`` / ``key:`` on the line, so a word in a
    # comment never judges the value before it and a placeholder-shaped value never hides a key.
    if cut := _UNQUOTED_END.search(body):
        stops.append(cut.start())
    span = min(stops) if stops else len(body)
    return body[:span].strip().rstrip(",;)}]").strip(), lead + span


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    shape: str


#: A percent escape: a line holding one is also judged URL-decoded (OVN-miassist-core-40).
_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def scan_text(text: str, path: str = "<string>") -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    for number, raw in enumerate(lines, start=1):
        # Confirmation round (OVN-miassist-core-40), 2026-11-16: a URL- or form-encoded line
        # (``redirect=...%3Fapi_key%3D<value>``) is judged as written and decoded.
        decoded = urllib.parse.unquote(raw) if _ESCAPE.search(raw) else raw
        for line in dict.fromkeys((raw, decoded)):
            _scan_line(line, number, lines, path, findings)
    return findings


def _scan_line(
    line: str, number: int, lines: list[str], path: str, findings: list[Finding]
) -> None:
    """Every finding on one line (``lines`` gives a YAML block value its next lines)."""
    for shape, pattern in SHAPES.items():
        judged_to = 0  # a key inside a value already judged is part of that value
        for match in pattern.finditer(line):
            if shape == "url_with_credentials" and PLACEHOLDER.match(match.group(2)):
                continue
            if shape == "bearer_token" and PLACEHOLDER.match(match.group(1)):
                continue
            if shape == "password_assignment":
                if match.start() < judged_to:
                    continue
                rest = line[match.end() :]
                value, span = whole_value(rest, lines[number : number + 3], match.group(2))
                judged_to = match.end() + span
                if len(value) < 3 or PLACEHOLDER.match(value) or (path, value) in KNOWN_BENIGN:
                    continue
            if (finding := Finding(path, number, shape)) not in findings:
                findings.append(finding)
