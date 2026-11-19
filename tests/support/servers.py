"""A built MCP server over fake apps, for in-process and HTTP tests."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from miassist.guidance.loader import Guidance
from miassist.runtime import build_runtime
from miassist.server.build import build_server
from miassist.server.specs import Deps
from miassist.tools import all_specs
from tests.support.app_factory import settings
from tests.support.fake_apps import FakeApp
from tests.support.memory_store import MemoryStore

APPS = ("miworkbench", "miserver", "midataworks", "miforge")
_GUIDANCE: list[Guidance] = []


def guidance() -> Guidance:
    if not _GUIDANCE:
        _GUIDANCE.append(Guidance())
    return _GUIDANCE[0]


def make_deps(
    installed: tuple[str, ...],
    fakes: dict[str, FakeApp] | None = None,
    store: Any = None,
    words: Guidance | None = None,
) -> Deps:
    urls = {f"{app}_url": f"http://{app}.test" for app in APPS}
    runtime = build_runtime(
        settings(apps=",".join(installed), **urls),
        transports={a: f.transport() for a, f in (fakes or {}).items()},
        store=store if store is not None else MemoryStore(),
    )
    return Deps(runtime=runtime, guidance=words or guidance())


def make_server(
    installed: tuple[str, ...],
    fakes: dict[str, FakeApp] | None = None,
    store: Any = None,
    *,
    words: Guidance | None = None,
    definitions: Any = None,
) -> tuple[MCPServer, Deps]:
    """The real server over ``fakes``; ``words`` and ``definitions`` replace the shipped guidance
    and playbook definitions (a temporary copy, for the drift and refusal tests)."""
    deps = make_deps(installed, fakes, store, words)
    return build_server(deps, all_specs(), definitions=definitions), deps


async def mark_reachable(deps: Deps) -> None:
    await deps.runtime.detector.probe_all()
