# Origin: miForge (Onegaishimas/miForge) backend/src/mcp_server/server.py @ e4251e4 (_strict_arguments,
# refuse_unknown_arguments). Mode: adapt (docs/REUSE.md). Changed: the refusal is the suite's one
# code, unknown_arguments (A37), in the result language's error text.
"""Every tool refuses an argument name it does not declare, naming the accepted ones; nothing runs
(PADR ADR-019; 001 FR-18). Applied server-wide once after registration, so no tool can opt out."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict, model_validator

from miassist.errors import render


def _strict(tool_name: str, base: type[ArgModelBase]) -> type[ArgModelBase]:
    accepted = sorted({field.alias or name for name, field in base.model_fields.items()})
    known = set(accepted) | set(base.model_fields)

    class Strict(base):  # type: ignore[valid-type, misc]
        model_config = ConfigDict(hide_input_in_errors=True, title=f"{tool_name} arguments")

        @model_validator(mode="before")
        @classmethod
        def _refuse_unknown(cls, data: Any) -> Any:
            if isinstance(data, dict):
                unknown = sorted(str(key) for key in data if key not in known)
                if unknown:
                    raise ValueError(
                        render(
                            "unknown_arguments",
                            f"{tool_name} does not take {', '.join(unknown)}; nothing was run",
                            f"use only: {', '.join(accepted) if accepted else 'no arguments'}",
                        )
                    )
            return data

    return Strict


def refuse_unknown_arguments(mcp: MCPServer) -> int:
    """Make every registered tool refuse undeclared argument names. Returns the count."""
    count = 0
    for tool in mcp._tool_manager.list_tools():
        tool.fn_metadata.arg_model = _strict(tool.name, tool.fn_metadata.arg_model)
        tool.parameters = {**tool.parameters, "additionalProperties": False}
        count += 1
    return count
