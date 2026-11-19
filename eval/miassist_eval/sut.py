"""Start the server under test (FR-002.15, FR-002.23, FR-002.35, FR-002.36; FTID §3.13).

- miAssist: Foundation's entry point, ``python -m miassist``, as a subprocess with ``MIASSIST_APPS``
  naming each replay or recorder listener (A5), and a fresh per-person key per run (PADR ADR-010).
  It is reached at ``/p/{key}/mcp``. The harness never imports the server package (FR-002.1).
- Baseline: three ``docker run`` of the digests in ``clients.lock.yaml``; a tag is refused. Not run
  tonight (needs Docker and the pinned digests, FTASKS 8.1).
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from miassist_eval import classes
from miassist_eval.classes import Refusal

EVAL_ROOT = Path(__file__).resolve().parents[1]
CLIENTS_LOCK = EVAL_ROOT / "clients.lock.yaml"
BASELINE_COMMANDS = {
    # miWorkbench/k8s/base/mcp.yaml:32; miForge/gitops/pilot/mcp.yaml:51; miDataworks' manifest.
    "miworkbench": ["python", "-m", "src.mcp_server"],
    "midataworks": ["python", "-m", "src.mcp_server"],
    "miforge": ["python", "-m", "mcp_server"],
}
BASELINE_AGENT = "agent:eval-baseline"


def fresh_key() -> str:
    """PADR ADR-010's format: 16 random bytes, 26 lowercase base32 characters without padding."""
    return base64.b32encode(secrets.token_bytes(16)).decode().rstrip("=").lower()


def miassist_env(app_urls: Mapping[str, str], base: Mapping[str, str]) -> dict[str, str]:
    """The server's environment: ``MIASSIST_APPS`` names each listener (A5)."""
    apps = ",".join(f"{app}={url}" for app, url in sorted(app_urls.items()))
    return {**base, "MIASSIST_APPS": apps}


def miassist_endpoint(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/p/{key}/mcp"


def baseline_images(lock: Path = CLIENTS_LOCK) -> dict[str, str]:
    """The baseline images, by digest only: a tag in place of a digest is refused (FTASKS 5.2)."""
    data = yaml.safe_load(lock.read_text(encoding="utf-8")) or {}
    images: dict[str, str] = {}
    for app, ref in (data.get("baseline_images") or {}).items():
        if not ref or "@sha256:" not in str(ref):
            raise Refusal(classes.CLIENT_NOT_STARTED, f"{app}: {ref!r} is not pinned by digest")
        images[app] = str(ref)
    return images


def baseline_run_args(
    app: str, image: str, run_id: str, token: str, backend_env: Mapping[str, str]
) -> list[str]:
    env = {**backend_env, "MCP_AUTH_TOKEN": token}
    if app in ("midataworks", "miforge"):
        env["MCP_AGENT_IDENTITY"] = BASELINE_AGENT
    argv = ["docker", "run", "--rm", "-d", "--name", f"eval-{run_id}-{app}", "--network", "host"]
    for k, v in sorted(env.items()):
        argv += ["-e", f"{k}={v}"]
    return [*argv, image, *BASELINE_COMMANDS[app]]


@dataclass
class Started:
    url: str
    info: dict[str, Any] = field(default_factory=dict)
