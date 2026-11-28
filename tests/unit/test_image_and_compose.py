"""The image and the Compose deployment path (PADR ADR-014; Foundation tasks 4.1, 6.8).

Nothing is built here: the Dockerfile's user and base tag, and the Compose file's shape, are read.
The first mirror build (Foundation 4.4) is the verification by building.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def dockerfile() -> list[str]:
    return [
        line.strip()
        for line in (REPO_ROOT / "Dockerfile").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_base_is_pinned_python_313_slim() -> None:
    bases = [line.split()[1] for line in dockerfile() if line.startswith("FROM ")]
    assert bases and all(b == "python:3.13-slim" for b in bases), bases
    assert not any(b.endswith(":latest") or ":" not in b for b in bases)


def test_runs_as_non_root_10001() -> None:
    users = [line for line in dockerfile() if line.startswith("USER ")]
    assert users == ["USER 10001:10001"]
    assert dockerfile()[-1] == 'CMD ["python", "-m", "miassist"]'


def test_no_compiler_in_the_final_stage() -> None:
    final = dockerfile()[
        max(i for i, line in enumerate(dockerfile()) if line.startswith("FROM ")) :
    ]
    joined = "\n".join(final)
    assert not re.search(r"\b(gcc|build-essential|g\+\+|make)\b", joined)
    assert "COPY --from=build /opt/venv /opt/venv" in final


def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    return loaded


def test_compose_services() -> None:
    assert set(compose()["services"]) == {"postgres", "migrate", "miassist"}


def test_compose_mounts_no_source() -> None:
    for name in ("migrate", "miassist"):
        service = compose()["services"][name]
        for volume in service.get("volumes", []):
            source = volume.split(":", 1)[0] if isinstance(volume, str) else volume.get("source")
            assert not str(source).startswith(("./src", "src", ".")), f"{name} mounts {source}"
        assert service["read_only"] is True
        assert service["environment"]["NVIDIA_VISIBLE_DEVICES"] == "void"


def test_compose_app_urls_unset_by_default() -> None:
    env = compose()["services"]["miassist"]["environment"]
    for app in ("MIWORKBENCH", "MISERVER", "MIDATAWORKS", "MIFORGE"):
        assert env[f"MIASSIST_{app}_URL"] == f"${{MIASSIST_{app}_URL:-}}"
    assert env["MIASSIST_APPS"] == "${MIASSIST_APPS:-}"


def test_env_example_lists_every_setting() -> None:
    from miassist.config import MiAssistSettings

    text = (REPO_ROOT / ".env.example").read_text()
    names = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    for field_name, field in MiAssistSettings.model_fields.items():
        env_name = field.alias or f"MIASSIST_{field_name.upper()}"
        assert env_name in names, f".env.example lacks {env_name}"
