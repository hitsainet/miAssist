"""The installed set (001 FR-1; AC-1.1, AC-1.2)."""

from __future__ import annotations

import logging

import pytest

from miassist.config import APP_IDS, InstalledSet

URL = "http://app.internal.example:8000"
SECRET_URL = "http://agent:hunter2-test-only@app:8000"


@pytest.mark.parametrize(
    ("raw", "urls", "names"),
    [
        ("miforge,unknownapp", {"miforge": URL}, "MIASSIST_APPS"),
        ("miforge,miforge", {"miforge": URL}, "MIASSIST_APPS"),
        ("miforge,miserver", {"miforge": URL}, "MIASSIST_MISERVER_URL"),
        ("midataworks", {"midataworks": SECRET_URL}, "MIASSIST_MIDATAWORKS_URL"),
    ],
    ids=["unknown", "duplicate", "listed-without-url", "credentials"],
)
def test_refusals(raw: str, urls: dict[str, str], names: str) -> None:
    with pytest.raises(SystemExit) as caught:
        InstalledSet.parse(raw, urls)
    message = str(caught.value)
    assert names in message
    assert URL not in message and "hunter2" not in message and "app:8000" not in message


def test_unlisted_url_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    installed = InstalledSet.parse("midataworks", {"midataworks": URL, "miforge": URL})
    assert installed == {"midataworks"}
    loud = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert not loud, [r.getMessage() for r in loud]
    assert all("miforge" not in r.getMessage() for r in caplog.records)
    assert any(r.levelno == logging.DEBUG for r in caplog.records)


def test_empty_set() -> None:
    assert InstalledSet.parse("", {}) == frozenset()
    assert InstalledSet.parse(" , ", {}).sorted() == []


def test_order_is_app_ids_order() -> None:
    all_four = InstalledSet.parse(
        "miforge,miserver,midataworks,miworkbench", dict.fromkeys(APP_IDS, URL)
    )
    assert all_four.sorted() == list(APP_IDS)
