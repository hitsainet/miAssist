"""FTASKS 4.5: the cassette secret scan, raw and base64; and every committed take is clean."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from miassist_eval import secret_scan

HF_VALUE = "hf_" + "A" * 34


@pytest.mark.parametrize(
    "text",
    [
        HF_VALUE,
        "Authorization: Bearer abcdefghijklmnopqrstuv",
        '{"api_key": "abcdef123456"}',
        "-----BEGIN RSA " + "PRIVATE KEY-----",
    ],
)
def test_raw_secrets_are_found(text: str) -> None:
    assert secret_scan.scan_bytes(text.encode())


def test_base64_secrets_are_found() -> None:
    blob = base64.b64encode(f"x {HF_VALUE} y".encode())
    assert any(
        f.startswith("base64:") for f in secret_scan.scan_bytes(b'{"body": "' + blob + b'"}')
    )


def test_a_listed_value_is_found_in_both_forms() -> None:
    value = "per-run-bearer-0f3a"
    assert secret_scan.scan_bytes(value.encode(), [value]) == ["listed value"]
    assert "base64:listed value" in secret_scan.scan_bytes(
        base64.b64encode(value.encode()), [value]
    )


def test_fixture_data_is_clean() -> None:
    assert secret_scan.scan_bytes(b'{"id": "evalfx-ds-1", "name": "evalfx-refund-messages"}') == []


def test_every_committed_take_is_clean(cassette_root: Path) -> None:
    assert secret_scan.scan_tree(cassette_root) == {}
