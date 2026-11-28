"""miAssist's settings (PADR ADR-015; Foundation task 2.2).

Every value comes from the environment with the prefix ``MIASSIST_`` (the database parts use the
``POSTGRES_*`` names the pod's Secret and ConfigMap carry). Foundation only LOADS values; the rules
that make an installed set valid (an unknown id, a listed app without a URL) are feature 001's FR-1.

Two rules hold already:

- **No credentials in a URL.** An app URL, or an explicit ``MIASSIST_DATABASE_URL``, carrying
  ``user:pass@`` refuses start. The database URL miAssist BUILDS from the ``POSTGRES_*`` parts is
  exempt: that password is the one secret (``miassist-secrets``), generated as hex (URL-safe).
- **A refusal never echoes the value** (``hide_input_in_errors=True``), so the URL with the
  credential in it is not printed into a log by the error that refuses it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Annotated, Final
from urllib.parse import quote, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: The four apps, sorted; also the order of every enum built from them (FTID §3.1).
APP_IDS: Final = ("miworkbench", "miserver", "midataworks", "miforge")

_log = logging.getLogger("miassist.config")


def _has_credentials(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.username is not None or parts.password is not None


class MiAssistSettings(BaseSettings):
    """The process's settings. Construct once in ``__main__`` and pass down."""

    model_config = SettingsConfigDict(
        env_prefix="MIASSIST_",
        hide_input_in_errors=True,
        extra="ignore",
        populate_by_name=True,
    )

    #: The raw ``MIASSIST_APPS`` comma list. Parsed by ``InstalledSet.parse`` (001 FR-1).
    apps: str = ""
    miworkbench_url: str | None = None
    miserver_url: str | None = None
    midataworks_url: str | None = None
    miforge_url: str | None = None

    #: An explicit database URL; when unset it is built from the ``POSTGRES_*`` parts.
    database_url_override: str | None = Field(default=None, alias="MIASSIST_DATABASE_URL")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="miassist", alias="POSTGRES_DB")
    postgres_user: str = Field(default="miassist", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD", repr=False)

    host: str = "0.0.0.0"
    port: int = 8765
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
    public_base_url: str | None = None
    health_interval_s: float = 60.0
    health_timeout_s: float = 3.0
    retention_days: int = 180
    max_request_body_bytes: int = 1_048_576
    max_pending_approvals: int = 10
    floor_limits: str | None = None
    large_import_bytes: int = 50_000_000_000
    #: 003 FPRD Q7: the public dataset ``owner/name[:config[:split]]`` the detector playbook
    #: proposes as everyday text when the person names none. Unset: the person is asked.
    everyday_text_repo: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][\w.-]*/[\w.-]+(:[\w.-]+){0,2}$"
    )

    @field_validator("everyday_text_repo", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator(
        "miworkbench_url", "miserver_url", "midataworks_url", "miforge_url", mode="before"
    )
    @classmethod
    def _app_url(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if _has_credentials(value):
                raise ValueError(
                    "an app URL must not carry credentials (user:pass@); miAssist holds none"
                )
        return value

    @field_validator("database_url_override", "public_base_url", mode="before")
    @classmethod
    def _plain_url(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if _has_credentials(value):
                raise ValueError(
                    "this URL must not carry credentials (user:pass@); the database password "
                    "comes from POSTGRES_PASSWORD"
                )
        return value

    def app_url(self, app: str) -> str | None:
        """The configured base URL of ``app`` (one of ``APP_IDS``), or ``None``."""
        if app not in APP_IDS:
            raise KeyError(app)
        url: str | None = getattr(self, f"{app}_url")
        return url

    @property
    def database_url(self) -> str:
        """The async SQLAlchemy URL: the override if set, else built from ``POSTGRES_*``."""
        if self.database_url_override:
            return self.database_url_override
        auth = quote(self.postgres_user, safe="")
        if self.postgres_password:
            auth += ":" + quote(self.postgres_password, safe="")
        return (
            f"postgresql+asyncpg://{auth}@{self.postgres_host}:{self.postgres_port}/"
            f"{self.postgres_db}"
        )


class InstalledSet(frozenset[str]):
    """The installed apps (001 FR-1; PADR ADR-007): configuration, detected but never inferred.

    ``parse`` refuses start, naming the variable and never echoing a URL, for an unknown id, a
    duplicate id, a listed app without a URL, or a URL carrying credentials. A URL for an app that
    is not listed is ignored with one DEBUG line: an app not listed is not installed, and nothing
    about it is registered, offered or logged above debug.
    """

    @classmethod
    def parse(cls, raw: str, urls: Mapping[str, str | None]) -> InstalledSet:
        ids = [part.strip() for part in raw.split(",") if part.strip()]
        seen: set[str] = set()
        for app in ids:
            if app not in APP_IDS:
                raise SystemExit(
                    f"config_refused: MIASSIST_APPS names an unknown app {app!r}; "
                    f"known: {', '.join(APP_IDS)}"
                )
            if app in seen:
                raise SystemExit(f"config_refused: MIASSIST_APPS lists {app!r} twice")
            seen.add(app)
            variable = f"MIASSIST_{app.upper()}_URL"
            url = urls.get(app)
            if not url:
                raise SystemExit(
                    f"config_refused: {app} is listed in MIASSIST_APPS but {variable} is unset"
                )
            if _has_credentials(url):
                raise SystemExit(f"config_refused: {variable} carries credentials (user:pass@)")
        for app in APP_IDS:
            if app not in seen and urls.get(app):
                _log.debug("an app URL is set but its app is not listed; ignored")
        return cls(seen)

    @classmethod
    def from_settings(cls, settings: MiAssistSettings) -> InstalledSet:
        return cls.parse(settings.apps, {app: settings.app_url(app) for app in APP_IDS})

    def sorted(self) -> list[str]:
        """The installed ids in ``APP_IDS`` order (the order of every enum)."""
        return [app for app in APP_IDS if app in self]
