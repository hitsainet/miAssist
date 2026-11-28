"""miServer's probe import conflict code (ENH-013 006, FR-006.7; ERROR_CODES_RELIED_ON).

Run in miServer's own interpreter on a ``git archive``: ``python -I -B <this> <archive root>``.
Reaches the raise site itself, ``ProbeService._dedupe_name`` with ``on_conflict="fail"`` and a
repository stub in which the name is taken, and prints the ``details.code`` miServer raises.
"""

import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])

from miserver.core.errors import ValidationError
from miserver.services.probe_service import ProbeService


class _Taken:
    async def get_by_name(self, name: str) -> object:
        return object()


class _Service:
    repository = _Taken()


found = []
try:
    asyncio.run(ProbeService._dedupe_name(_Service(), "evalfx-probe", "fail"))  # type: ignore[arg-type]
except ValidationError as exc:
    found.append([exc.details.get("code"), exc.status_code])
print(json.dumps(found))
