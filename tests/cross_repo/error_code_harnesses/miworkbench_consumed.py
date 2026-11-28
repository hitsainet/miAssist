"""miWorkbench's refusal of an approval that was already used (ENH-013 006, FR-006.7; MAP-2).

Run in miWorkbench's own interpreter on a ``git archive``: ``python -I -B <this> <archive backend>``.
Calls ``mcp_approvals.consume`` (the spend the REST gate runs) for an approved caller-executed
request whose conditional update finds it no longer ``approved``, with a session stub whose
refresh reads back the status a spent approval holds (``ApprovalStatus.CONSUMED``), and prints the
409's ``detail.status``: miWorkbench sends a status there, not a code (PRE-006).
"""

import asyncio
import json
import sys
from typing import ClassVar

sys.path.insert(0, sys.argv[1])

from fastapi import HTTPException
from src.api.v1.endpoints import mcp_approvals as m

tool = next(t for t, (kind, _) in m.APPROVABLE_TOOLS.items() if kind is m.Execution.CALLER)


class _Approval:
    id = "apr_evalfx"
    tool_name = tool
    payload: ClassVar[dict[str, int]] = {"evalfx": 1}
    status = m.ApprovalStatus.APPROVED.value
    reason = None


approval = _Approval()


async def _get(db: object, request_id: str) -> _Approval:
    return approval


async def _nothing(db: object) -> None:
    return None


class _NoRow:
    def scalar_one_or_none(self) -> None:
        return None


class _Session:
    async def execute(self, *args: object, **kwargs: object) -> _NoRow:
        return _NoRow()

    async def rollback(self) -> None:
        return None

    async def refresh(self, row: _Approval) -> None:
        row.status = m.ApprovalStatus.CONSUMED.value

    async def commit(self) -> None:
        return None


m._get_or_404 = _get
m.expire_stale = _nothing
found = []
try:
    asyncio.run(m.consume(_Session(), approval.id, tool, {"evalfx": 1}))
except HTTPException as exc:
    found.append([exc.detail["status"], exc.status_code])
print(json.dumps(found))
