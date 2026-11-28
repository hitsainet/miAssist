"""A URL carrying credentials refuses start, without echoing the value (ADR-015; Foundation 2.5).

The database URL BUILT from the ``POSTGRES_*`` parts carries the one secret and is exempt.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from miassist.config import MiAssistSettings

SECRET = "hunter2-test-only"


@pytest.mark.parametrize(
    "variable",
    [
        "MIASSIST_MIWORKBENCH_URL",
        "MIASSIST_MISERVER_URL",
        "MIASSIST_MIDATAWORKS_URL",
        "MIASSIST_MIFORGE_URL",
        "MIASSIST_DATABASE_URL",
        "MIASSIST_PUBLIC_BASE_URL",
    ],
)
def test_credentials_refused(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    scheme = "postgresql+asyncpg" if variable == "MIASSIST_DATABASE_URL" else "http"
    monkeypatch.setenv(variable, f"{scheme}://agent:{SECRET}@host:8000/x")
    with pytest.raises(ValidationError) as caught:
        MiAssistSettings()
    assert SECRET not in str(caught.value)
    assert "credentials" in str(caught.value)


def test_plain_urls_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIASSIST_MISERVER_URL", "http://miserver-backend:8000")
    monkeypatch.setenv("MIASSIST_MIFORGE_URL", "")
    settings = MiAssistSettings()
    assert settings.miserver_url == "http://miserver-backend:8000"
    assert settings.miforge_url is None


def test_built_database_url_carries_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "abc-test-only")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.delenv("MIASSIST_DATABASE_URL", raising=False)
    url = MiAssistSettings().database_url
    assert url == "postgresql+asyncpg://miassist:abc-test-only@postgres:5432/miassist"


def test_app_urls_unset_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for app in ("MIWORKBENCH", "MISERVER", "MIDATAWORKS", "MIFORGE"):
        monkeypatch.delenv(f"MIASSIST_{app}_URL", raising=False)
    monkeypatch.delenv("MIASSIST_APPS", raising=False)
    settings = MiAssistSettings()
    assert settings.apps == ""
    assert all(
        settings.app_url(a) is None for a in ("miworkbench", "miserver", "midataworks", "miforge")
    )
    assert (settings.port, settings.health_interval_s, settings.health_timeout_s) == (8765, 60, 3)
