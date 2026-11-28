"""Entry point: ``python -m miassist`` (Foundation task 4.2).

- ``MIASSIST_MIGRATE=1`` (the init container): run the Alembic migrations to head and exit.
- Otherwise serve with uvicorn, **with ``access_log=False``** (R1M-19): uvicorn's default access log
  prints request paths, and ``/p/<key>/mcp`` carries the per-person key. The SDK's logger runs at
  WARNING (it logs call arguments at debug; ADR-016).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def alembic_dir() -> Path:
    """The Alembic environment: ``MIASSIST_ALEMBIC_DIR``, else ``alembic/`` beside ``src/`` (a
    checkout), else ``/app/alembic`` (the image). Refuses by name when none holds ``env.py``."""
    candidates = [
        (
            Path(os.environ["MIASSIST_ALEMBIC_DIR"])
            if os.environ.get("MIASSIST_ALEMBIC_DIR")
            else None
        ),
        Path(__file__).resolve().parents[2] / "alembic",
        Path("/app/alembic"),
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "env.py").is_file():
            return candidate
    raise SystemExit("migrations_missing: no Alembic environment found (set MIASSIST_ALEMBIC_DIR)")


def migrate() -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir()))
    command.upgrade(cfg, "head")
    return 0


def main() -> int:
    from miassist import logging as ma_logging

    ma_logging.configure()
    if os.environ.get("MIASSIST_MIGRATE") == "1":
        return migrate()

    import uvicorn

    from miassist.app import create_app
    from miassist.config import MiAssistSettings

    settings = MiAssistSettings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_config=None,
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
