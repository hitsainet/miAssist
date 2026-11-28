"""miWorkbench's gate refusal of a call that differs from what was approved (ENH-013 006, FR-006.7).

Run in miWorkbench's own interpreter on a ``git archive``: ``python -I -B <this> <archive backend>``.
Calls the gate's ``_consume_and_commit`` with the consume refusing the payload (422) and a session
stub, and prints the ``detail.code`` and status the gate turns it into.
"""

import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])

from fastapi import HTTPException
from src.api.v1.endpoints import mcp_approvals
from src.core import approval_gate, database


async def _differs(*args: object) -> None:
    raise HTTPException(422, "the payload differs from the one the operator approved")


class _Session:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> bool:
        return False


mcp_approvals.consume = _differs
database.AsyncSessionLocal = lambda: _Session()
found = []
try:
    asyncio.run(approval_gate._consume_and_commit("apr_evalfx", "evalfx_tool", {}))
except HTTPException as exc:
    found.append([exc.detail["code"], exc.status_code])
print(json.dumps(found))
