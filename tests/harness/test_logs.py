"""No argument value, raw key or ``Authorization`` value in any log line (001 FR-20, AC-20.3;
FTASKS 12.6; R1M-22, R1M-25).

Logging is configured exactly as the entry point configures it (``miassist.logging.configure``:
levels, the JSON formatter and the sensitive-field filter), with the handler's stream swapped for
a buffer. Every recorded scenario (``tests/support/scenarios.py``) runs on a keyed path with a
bearer token, and every installed set runs the guide and the status: each output line is scanned
for the raw key, the token, and every distinctive argument value; every audit line carries
``key_fp`` (eight hexadecimal characters) or null.
"""

from __future__ import annotations

import io
import itertools
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote, quote_plus

import pytest

from miassist import logging as ma_logging
from tests.support.scenarios import APPS, Scenario, run, scenarios

KEY = "qwertyuiopasdfghjklzxcvbnm"
BEARER = "Bearer test-only-token-value-4471"
#: Argument values too common to be evidence of a leak (they are words in other log text).
COMMON = frozenset(APPS) | {"start", "apps", "playbooks", "results", "glossary", "connect"}
KEY_FP = re.compile(r"^[0-9a-f]{8}$")


@contextmanager
def production_logs() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    named = {n: logging.getLogger(n).level for n in ("mcp", "httpx", "httpx2", "httpcore")}
    buffer = io.StringIO()
    ma_logging.configure()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(ma_logging.make_handler(buffer))
    try:
        yield buffer
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
        for name, level in named.items():
            logging.getLogger(name).setLevel(level)
        logging.getLogger("uvicorn.access").disabled = False


def encoded_forms(value: str) -> set[str]:
    """The raw value and every form a log line could carry it in (memory
    ``leak-tests-must-look-for-the-encoded-form``; R1 review fix OR1-001-10)."""
    forms = {
        value,
        quote(value, safe=""),
        quote(value),
        quote_plus(value),
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
    }
    return {f for f in forms if f}


def values_of(args: dict[str, Any]) -> list[str]:
    out = []
    for value in args.values():
        if isinstance(value, str) and len(value) >= 4 and value not in COMMON:
            out += sorted(encoded_forms(value))
    return out


def check(lines: list[str], args: dict[str, Any], where: str) -> int:
    audits = 0
    for line in lines:
        assert KEY not in line, (where, line)
        assert BEARER not in line and "test-only-token" not in line, (where, line)
        for value in values_of(args):
            assert value not in line, (where, value, line)
        record = json.loads(line)
        if record.get("logger") == "miassist.audit":
            audits += 1
            assert "key_fp" in record, (where, line)
            assert record["key_fp"] is None or KEY_FP.match(record["key_fp"]), (where, line)
    return audits


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s.id)
def test_no_values_keys_or_auth(scenario: Scenario) -> None:
    with production_logs() as buffer:
        run(scenario, key=KEY, headers={"authorization": BEARER})
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    audits = check(lines, scenario.args, scenario.id)
    assert audits == 1, (scenario.id, audits)
    audit = next(json.loads(x) for x in lines if '"miassist.audit"' in x)
    assert audit["key_fp"] is not None and audit["tool"] == scenario.tool


COMBINATIONS = [c for n in range(5) for c in itertools.combinations(APPS, n)]


@pytest.mark.parametrize("installed", COMBINATIONS, ids=lambda c: "+".join(c) or "empty")
def test_sixteen_configurations_log_nothing_sensitive(installed: tuple[str, ...]) -> None:
    with production_logs() as buffer:
        for tool, args in (("miassist_guide", {}), ("miassist_status", {})):
            run(Scenario("cfg", installed, tool, args), headers={"authorization": BEARER})
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert check(lines, {}, "+".join(installed)) == 2


def test_the_scan_bites() -> None:
    """The checks themselves: a planted value, key, token or a renamed fingerprint is caught."""
    line = json.dumps({"logger": "miassist.audit", "key_fp": None, "message": "x"})
    for planted in (KEY, BEARER, "fx-approval-1"):
        bad = json.dumps({"logger": "x", "message": planted})
        with pytest.raises(AssertionError):
            check([bad], {"approval_id": "fx-approval-1"}, "plant")
    with pytest.raises(AssertionError):
        check([json.dumps({"logger": "miassist.audit", "key": "abc"})], {}, "renamed")
    encoded = json.dumps({"logger": "httpx", "message": "GET /api/v1/approvals/fx%20a%2Fb%C3%B6"})
    with pytest.raises(AssertionError):
        check([encoded], {"approval_id": "fx a/bö"}, "percent-encoded")
    escaped = json.dumps({"logger": "x", "message": "fx a/b\u00f6"})
    with pytest.raises(AssertionError):
        check([escaped], {"approval_id": "fx a/bö"}, "json-escaped")
    assert check([line], {}, "ok") == 1
