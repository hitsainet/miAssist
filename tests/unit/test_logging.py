"""The log filter drops sensitive fields and keeps ``key_fp`` (ADR-016; Foundation task 2.4)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from miassist.logging import DROPPED_FIELDS, key_fingerprint, make_handler


def _emit(**extra: object) -> dict[str, object]:
    stream = io.StringIO()
    logger = logging.getLogger("miassist.test_logging")
    logger.handlers = [make_handler(stream)]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("tool call", extra=extra)
    line = stream.getvalue().strip()
    assert line, "nothing was emitted"
    record: dict[str, object] = json.loads(line)
    return record


@pytest.mark.parametrize("field", ["authorization", "key", "arguments", "body"])
def test_sensitive_field_dropped(field: str) -> None:
    record = _emit(**{field: "SENSITIVE-VALUE"}, tool="miassist_guide")
    assert field not in record
    assert "SENSITIVE-VALUE" not in json.dumps(record)
    assert record["tool"] == "miassist_guide"


def test_key_fp_kept() -> None:
    fp = key_fingerprint("0123456789abcdef" * 4)
    assert fp == "01234567"
    assert _emit(key_fp=fp)["key_fp"] == "01234567"


def test_dropped_names_exact() -> None:
    assert DROPPED_FIELDS == {"authorization", "key", "arguments", "body"}
    assert "key_fp" not in DROPPED_FIELDS
