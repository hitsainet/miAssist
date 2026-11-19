"""The MCP server's assembly (PADR ADR-003, ADR-019; 001 FR-3, FR-10, FR-18; FTID §3.9).

``build_server`` registers every offered ``ToolSpec`` (filtered by the installed set, in sorted
name order, never changed afterwards), with its title and description from ``guidance/tools.yaml``,
explicit ``readOnlyHint``/``destructiveHint`` (A13; ``idempotentHint``/``openWorldHint`` unset), the
audit wrapper, and strict arguments. It renders the server instructions from the installed set and
serves the glossary as ``miassist://glossary/{key}``. ``build_mcp_app`` returns the stateless,
JSON-response streamable-HTTP app with ``host`` and the deployment's allowed hosts: the SDK's default
turns on DNS-rebinding protection with a loopback-only ``Host`` list
(``miForge/backend/src/mcp_server/server.py:263-272`` records the same trap).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from importlib.resources.abc import Traversable
from typing import Any, Final

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts.base import Prompt
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette

from miassist import __version__
from miassist.config import MiAssistSettings
from miassist.playbooks import generate
from miassist.playbooks.registry import PlaybookError, PlaybookRegistry, load
from miassist.playbooks.status import PROVIDERS
from miassist.server.audit import audited
from miassist.server.keyshim import key_from_scope
from miassist.server.specs import Deps, ToolSpec
from miassist.server.strict_args import refuse_unknown_arguments

SERVER_NAME: Final = "miassist"
INSTRUCTIONS_MAX: Final = 4096
INSTRUCTIONS_HEAD: Final = 512


def render_instructions(deps: Deps) -> str:
    names = [deps.guidance.app_name(a) for a in deps.runtime.installed.sorted()]
    if not names:
        installed = "no app yet"
    elif len(names) == 1:
        installed = names[0]
    else:
        installed = ", ".join(names[:-1]) + " and " + names[-1]
    text = deps.guidance.render(
        deps.guidance.instructions, {"installed_apps": installed, "installed_count": len(names)}
    ).text
    if len(text) >= INSTRUCTIONS_MAX:
        raise RuntimeError("the server instructions must stay under 4,096 characters")
    return text


def _key_hash(kwargs: dict[str, Any]) -> str | None:
    ctx = kwargs.get("ctx")
    request = getattr(getattr(ctx, "request_context", None), "request", None) if ctx else None
    key = key_from_scope(getattr(request, "scope", None))
    return hashlib.sha256(key.encode()).hexdigest() if key else None


def load_playbooks(
    deps: Deps, tool_names: Sequence[str], definitions: Traversable | None = None
) -> PlaybookRegistry:
    """The playbook registry for this installation (FR-5, AC-5.4); every definition needs a
    status provider (FR-23), or start is refused."""
    registry = load(deps.guidance, deps.runtime.installed, tool_names, definitions)
    for playbook_id in registry.playbooks:
        if playbook_id not in PROVIDERS:
            raise PlaybookError(f"playbook_invalid: {playbook_id} has no status provider")
    return registry


def register_playbook_forms(mcp: MCPServer, deps: Deps) -> None:
    """One prompt per OFFERED playbook, named by its id (AC-5.6), and the skill resource
    (``miassist://skills/<id>``). Both render from the registry at each request: nothing is cached
    (AC-5.5)."""
    registry = deps.playbooks
    if registry is None:
        raise RuntimeError("the playbook registry is not loaded")
    for playbook in registry.offered:

        def make(playbook_id: str) -> Any:
            def prompt() -> str:
                current = registry.get(playbook_id)
                if current is None:
                    raise ValueError(f"unknown_playbook: {playbook_id}")
                return generate.prompt_text(deps.guidance, current)

            return prompt

        mcp.add_prompt(
            Prompt.from_function(
                make(playbook.id),
                name=playbook.id,
                title=playbook.title,
                description=playbook.goal,
            )
        )

    @mcp.resource(
        "miassist://skills/{playbook_id}",
        name="skill",
        title="Playbook skill",
        description="A playbook on offer here, as a skill (SKILL.md).",
        mime_type="text/markdown",
    )
    def skill(playbook_id: str) -> str:
        current = registry.get(playbook_id)
        if current is None or not current.offered:
            raise ValueError(f"unknown_playbook: no playbook {playbook_id!r} is on offer here")
        return generate.skill_markdown(deps.guidance, current)


def build_server(
    deps: Deps, specs: Sequence[ToolSpec], *, definitions: Traversable | None = None
) -> MCPServer:
    """The MCP server with every offered tool registered, in sorted order, the playbook registry
    loaded and each offered playbook's prompt registered."""
    mcp: MCPServer = MCPServer(
        SERVER_NAME, instructions=render_instructions(deps), version=__version__
    )
    installed = frozenset(deps.runtime.installed)
    offered = sorted((s for s in specs if s.offered(installed)), key=lambda s: s.name)
    deps.playbooks = load_playbooks(deps, [s.name for s in offered], definitions)
    for spec in offered:
        text = deps.guidance.tools.tools[spec.name]
        function = spec.make(deps)
        deps.tool_functions[spec.name] = function
        mcp.add_tool(
            audited(spec.name, function, _key_hash),
            name=spec.name,
            title=text.title,
            description=text.description,
            annotations=ToolAnnotations(
                title=text.title, readOnlyHint=spec.read_only, destructiveHint=spec.destructive
            ),
        )
    register_playbook_forms(mcp, deps)
    refuse_unknown_arguments(mcp)
    glossary = deps.guidance.glossary

    @mcp.resource(
        "miassist://glossary/{key}",
        name="glossary",
        title="Glossary entry",
        description="One glossary entry.",
        mime_type="text/markdown",
    )
    def glossary_entry(key: str) -> str:
        entry = glossary.get(key)
        if entry is None:
            raise ValueError(f"unknown_term: no glossary entry {key!r}")
        return f"# {entry.term}\n\n{entry.plain}\n\n{entry.short}\n"

    return mcp


def transport_security(settings: MiAssistSettings) -> TransportSecuritySettings:
    """DNS-rebinding protection ON, with the deployment's hostnames allowed (any port)."""
    hosts: list[str] = []
    origins: list[str] = []
    for host in settings.allowed_hosts:
        hosts += [host, f"{host}:*"]
        origins += [f"https://{host}", f"http://{host}", f"https://{host}:*", f"http://{host}:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


def build_mcp_app(mcp: MCPServer, settings: MiAssistSettings) -> Starlette:
    """The streamable-HTTP ASGI app: stateless, one JSON body per request, served at ``/mcp``."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=settings.host,
        transport_security=transport_security(settings),
    )
