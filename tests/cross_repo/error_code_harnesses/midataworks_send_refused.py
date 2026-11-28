"""miDataworks' detector-set send refusal (ENH-013 006, FR-006.7).

Run in miDataworks' own interpreter on a ``git archive``: ``python -I -B <this> <archive backend>``.
A refusing check makes ``send_service`` raise ``DetectorSetError("send_refused", ...)``; this
raises that error the way the service does and prints its code and the status the family maps it to
(``services/detector_sets/errors.py``, ``CODES``), so a renamed or removed code is refused by the
sibling's own error class.
"""

import json
import os
import sys

from cryptography.fernet import Fernet

# Placeholder settings for IMPORTING miDataworks (never to connect), as scripts/snapshot_openapi.py.
os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
sys.path.insert(0, sys.argv[1])

from src.services.detector_sets import errors

found = []
try:
    raise errors.DetectorSetError("send_refused", "a check refused", {"checks": []})
except errors.DetectorSetError as exc:
    if exc.code in errors.CODES:
        found.append([exc.code, exc.status_code])
print(json.dumps(found))
