"""No committed (or about-to-be-committed) file carries a credential (Foundation task 1.7).

Scans every file git tracks plus every untracked file not ignored, so a planted credential is
caught before its commit. The self-test plants each known shape and requires it caught; a scanner
that stops recognising one shape is a guard that passes forever.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.support.secret_scan import SHAPES, scan_text

REPO_ROOT = Path(__file__).resolve().parents[2]
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf"}
#: The scanner and its self-test necessarily spell the shapes.
EXEMPT = {"tests/support/secret_scan.py", "tests/unit/test_no_secrets_tracked.py"}


def candidate_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted(
        name
        for name in out.split("\0")
        if name
        and name not in EXEMPT
        and Path(name).suffix not in BINARY_SUFFIXES
        and (REPO_ROOT / name).is_file()
    )


def test_tree_is_scanned() -> None:
    assert len(candidate_files()) > 20


def test_no_credential_in_any_file() -> None:
    findings = []
    for name in candidate_files():
        try:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings += scan_text(text, name)
    assert not findings, "credentials found:\n" + "\n".join(
        f"{f.path}:{f.line} ({f.shape})" for f in findings
    )


PLANTED = {
    "github_token": "token = 'ghp_" + "A" * 36 + "'",
    "huggingface_token": "HF = hf_" + "b" * 34,
    "aws_access_key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "slack_token": "xoxb-" + "1234567890-abcdef",
    "private_key": "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
    "anthropic_or_openai_key": "key: sk-ant-" + "x1" * 20,
    "url_with_credentials": "postgresql://miassist:" + "s3cr3tvalue@db:5432/x",
    "password_assignment": "POSTGRES_PASSWORD=" + "abc123def456",
    # Confirmation fix (C-001-2), 2026-11-16.
    "bearer_token": "Authorization: Bearer " + "s3cr3tvalue42abcxyz",
}


def test_every_shape_has_a_plant() -> None:
    assert set(PLANTED) == set(SHAPES)


@pytest.mark.parametrize("shape", sorted(PLANTED))
def test_planted_shape_is_caught(shape: str) -> None:
    assert shape in {f.shape for f in scan_text(PLANTED[shape])}


@pytest.mark.parametrize(
    "line",
    [
        "POSTGRES_PASSWORD=",
        'POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"',
        "POSTGRES_PASSWORD=miassist-test-only",
        'kubectl create secret --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)"',
        "password = settings.postgres_password",
        "POSTGRES_PASSWORD=<generated>",
        "url = 'postgresql+asyncpg://${USER}:${POSTGRES_PASSWORD}@db/x'",
    ],
)
def test_placeholders_pass(line: str) -> None:
    assert not scan_text(line), scan_text(line)


#: R2 review fix (OR2-001-1), 2026-11-16: the reviewer's ten real values (the first ten), then
#: values that start with or are a short English word, YAML block scalars, escaped JSON and a
#: second key after an empty one. Each must be caught; the round-1 article rule missed eight.
REAL_VALUES = [
    'MIASSIST_DB_PASSWORD="the horse battery staple"',
    "PASSWORD='and correct horse battery'",
    'PASSWORD="a correct horse battery"',
    "password: the correctHorseBatteryStaple",
    "HF_TOKEN=the",
    "token: a1b2c3d4e5f6a7b8",
    "token: theQm9iIGlzIGEgc2VjcmV0",
    '{"token": "s3cr3tvalue42"}',
    '{"api_key": "s3cr3tvalue42"}',
    '  "hf_token": "s3cr3tvalue42abc",',
    "PASSWORD=a horse battery staple",
    "token: a staple horse battery",
    "secret: an apple a day",
    "TOKEN=THE",
    "SECRET: its-actual-value-9f8e7d",
    "API_KEY=andThisIsBase64Secret==",
    "Never takes a token: the correctHorseBatteryStaple",
    "token: |\n  ghq9f8e7d6c5b4a3s3cr3t",
    "secret: >-\n  9f8e7d6c5b4a3s3cr3tvalue",
    '{\\"password\\": \\"s3cr3tvalue42\\"}',
    '{"name": "x", "token": "", "secret": "s3cr3tvalue"}',
]


@pytest.mark.parametrize("line", REAL_VALUES)
def test_real_value_is_caught(line: str) -> None:
    assert scan_text(line), line


def test_known_prose_passes_only_in_its_own_file() -> None:
    """The false positive behind the round-1 loosening is allowed by its exact text in its own
    file (KNOWN_BENIGN), never by a word rule: the same sentence elsewhere, or with a different
    value, is still a finding."""
    from tests.support.secret_scan import KNOWN_BENIGN
    from tests.support.source_tree import source_present

    path = "tests/fixtures/openapi/midataworks.json"
    ((value,),) = [(v,) for p, v in KNOWN_BENIGN if p == path]
    line = f'"description": "Never takes a token: {value}",'
    assert scan_text(line, path) == []
    assert scan_text(line, "elsewhere.json"), "allowed outside its own file"
    assert scan_text(line.replace("the operator's", "the hunter2 is"), path)
    # Every entry names a real file. On the mirror snapshot an entry for a file the sync strips
    # (``0xcc/``) is reported and passed over; anywhere else a missing file fails (mirror fix 001-M).
    for known_path, _ in KNOWN_BENIGN:
        if source_present(known_path):
            assert (REPO_ROOT / known_path).is_file(), known_path


def test_no_word_rule_exempts_a_value() -> None:
    """No placeholder rule matches an English article or conjunction on its own."""
    from tests.support.secret_scan import PLACEHOLDER

    for word in ("the", "and", "its", "THE", "a horse", "the horse battery staple"):
        assert not PLACEHOLDER.match(word), word


#: R3 review fix (OR3-001-1), 2026-11-16 (the reviewer's proposed test, folded in here because this
#: file is exempt from the tree scan): each line was caught before R2's whole-value rule and missed
#: after it. An unquoted value ends at a trailing comment or before the next key on the line, so a
#: comment word never judges the value before it and a placeholder-shaped value never hides a key.
LATER_PLACEHOLDER_WORD = [
    "export API_KEY=9f8e7d6c5b4a3210ffee  # example key",
    "password: s3cr3tvalue42abc  # example only",
    "DB_PASSWORD=s3cr3tvalue42abc # changeme before prod",
    "HF_TOKEN=s3cr3tvalue42abc # not test-only",
    "DB_PASSWORD=settings.db; API_KEY=s3cr3tvalue42abc",
    "TOKEN=$HOME API_KEY=s3cr3tvalue42abc",
    "TOKEN=os.environ.get('X'); SECRET=s3cr3tvalue42abc",
    # two key spellings the scanner did not know (found while re-running round 3's cases)
    "ACCESS_KEY=s3cr3tvalue42abc",
    "api-key: s3cr3tvalue42abc",
    # the same, with a non-credential key or a comment holding the second key
    "TOKEN=$HOME # API_KEY=s3cr3tvalue42abc",
    'password: settings.db "secret": "s3cr3tvalue42abc"',
]
_EVAL = "0xcc/tids/002_FTID|Evaluation.md"
NEAR_MISSES = [
    ("token: GitHub's  own job token", _EVAL),  # inner whitespace differs
    ("token: github's own job token", _EVAL),  # case differs
    ("token: GitHub's own job token", "src/miassist/x.py"),  # another path
    ("token: GitHub's own job token; PASSWORD=s3cr3tvalue42abc", _EVAL),
]


@pytest.mark.parametrize("line", LATER_PLACEHOLDER_WORD)
def test_a_later_placeholder_word_hides_nothing(line: str) -> None:
    assert scan_text(line), line


@pytest.mark.parametrize(("line", "path"), NEAR_MISSES)
def test_allow_list_is_exact(line: str, path: str) -> None:
    assert scan_text(line, path), (line, path)


def test_allowed_value_passes_only_at_its_path() -> None:
    assert scan_text("token: GitHub's own job token", _EVAL) == []


@pytest.mark.parametrize(
    "line",
    [
        "API_KEY=$API_KEY  # example: set it in .env",
        "POSTGRES_PASSWORD=miassist-test-only  # the local test container",
        "TOKEN=${TOKEN} OTHER=1",
    ],
)
def test_a_comment_or_second_key_never_flags_a_placeholder(line: str) -> None:
    assert not scan_text(line), scan_text(line)


#: Confirmation fix (C-001-1, C-001-2), 2026-11-16 (the confirmer's proposed test, folded in here
#: because this file is exempt from the tree scan). C-001-1: a placeholder-shaped first value still
#: hid a later key joined by ``;`` or ``&`` with no space (each line was caught before 49b0766 and
#: missed at 2ba29db). C-001-2: ordinary credential spellings the scanner never knew: camelCase
#: ``apiKey`` / ``accessKey``, ``private_key``, and an HTTP bearer credential in any text.
_SV = "s3cr3tvalue42abc"
JOINED = [
    "DB_PASSWORD=settings.db;API_KEY=" + _SV,
    "TOKEN=$HOME;API_KEY=" + _SV,
    "TOKEN=$HOME&&API_KEY=" + _SV,
    "TOKEN=os.environ.get('X');SECRET=" + _SV,
    "Server=db;User Id=sa;Token=${T};Password=" + _SV + ";",
    "https://host/x?token=$T&api_key=" + _SV,
]
SPELLINGS = [
    '{"apiKey": "' + _SV + '"}',
    "apikey=" + _SV,
    '{"accessKey": "' + _SV + '"}',
    "private_key: " + _SV,
    "Authorization: Bearer " + _SV + "xyz",
    'headers = {"Authorization": "Bearer ' + _SV + 'xyz"}',
    "curl -H 'authorization: bearer " + _SV + "xyz' https://h",
]
BEARER_BENIGN = [
    "Authorization: Bearer ${SYNC_TOKEN}",
    "Authorization: Bearer <your-token-here>",
    "Use bearer authentication for every request",
    # token-shaped, but a placeholder (the shape's placeholder skip is load-bearing)
    "Authorization: Bearer example-token-12345678",
    # an identifier in prose after the word (no digit: the shape requires one)
    "the middleware reads the Bearer AuthorizationHeaderValue",
]


@pytest.mark.parametrize("line", JOINED)
def test_a_placeholder_never_hides_a_joined_key(line: str) -> None:
    assert scan_text(line), line


@pytest.mark.parametrize("line", SPELLINGS)
def test_ordinary_credential_spellings_are_caught(line: str) -> None:
    assert scan_text(line), line


@pytest.mark.parametrize("line", BEARER_BENIGN)
def test_placeholders_and_prose_pass(line: str) -> None:
    assert scan_text(line) == [], line


def test_a_semicolon_inside_a_value_does_not_shorten_it() -> None:
    """Only a following ``key=`` cuts a value: ``ab;cdefgh`` is judged whole (a cut at the ``;``
    would leave a 2-character value the scanner skips)."""
    assert scan_text("PASSWORD=ab;cdefgh")


#: OVN-miassist-core-40 (confirmation round), 2026-11-16: two more of the confirmer's cases the
#: verified fix still missed: a backtick-quoted value, and a key and value URL- or form-encoded.
ENCODED = [
    "PASSWORD=`" + _SV + "`",
    "const password = `" + _SV + "`;",
    "redirect=https%3A%2F%2Fhost%2Fx%3Fapi_key%3D" + _SV,
    "curl 'https://host/x?token=$TOKEN&api_key=" + _SV + "'",
    "next=%2Fcallback%3Ftoken%3D" + _SV,
]
ENCODED_BENIGN = [
    "set `POSTGRES_PASSWORD=` in `.env`",
    "export TOKEN=`cat $TOKEN_FILE`",
    "redirect=https%3A%2F%2Fhost%2Fx%3Ftoken%3D%24%7BTOKEN%7D",
    "a 100%25 reliable token: ${TOKEN}",
]


@pytest.mark.parametrize("line", ENCODED)
def test_a_backticked_or_encoded_value_is_caught(line: str) -> None:
    assert scan_text(line), line


@pytest.mark.parametrize("line", ENCODED_BENIGN)
def test_a_backticked_or_encoded_placeholder_passes(line: str) -> None:
    assert scan_text(line) == [], scan_text(line)


def test_one_finding_per_line_and_shape() -> None:
    """A line judged as written and decoded is reported once."""
    line = "token=" + _SV + "&next=%2Fx"
    assert scan_text(line) == [scan_text(line)[0]]
