"""Shared pieces of the two contract modules (001 FTASKS 1.1, 1.2)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, RootModel

from miassist.errors import ERROR_CODE_MAX, ERROR_CODE_PATTERN

TOOL_NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,128}$"


def not_null(schema: dict[str, Any]) -> None:
    """``json_schema_extra`` for an OPTIONAL field that is absent, never ``null``: drops the null
    branch and the ``default: null`` Pydantic writes for ``X | None = None``."""
    schema.pop("default", None)
    branches = schema.get("anyOf")
    if branches is not None:
        kept = [b for b in branches if b != {"type": "null"}]
        if len(kept) == 1:
            schema.pop("anyOf")
            schema.update(kept[0])


def optional(**kwargs: Any) -> Any:
    """A field that may be absent but, when present, is never ``null``."""
    return Field(default=None, json_schema_extra=not_null, **kwargs)


class AppId(StrEnum):
    """One of the suite's four apps."""

    MIWORKBENCH = "miworkbench"
    MISERVER = "miserver"
    MIDATAWORKS = "midataworks"
    MIFORGE = "miforge"


class ToolName(RootModel[Annotated[str, Field(pattern=TOOL_NAME_PATTERN)]]):
    """An MCP tool's name."""


class ErrorCode(
    RootModel[Annotated[str, Field(pattern=ERROR_CODE_PATTERN, max_length=ERROR_CODE_MAX)]]
):
    """An error code: lower case, one optional dotted app prefix, at most 64 characters. An app's
    own code in any other case is lower-cased here and keeps its spelling in the original text."""
