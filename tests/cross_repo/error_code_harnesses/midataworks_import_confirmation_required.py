"""miDataworks' large-import confirmation code (ENH-013 006, FR-006.7).

Run in miDataworks' own interpreter on a ``git archive``: ``python -I -B <this> <archive backend>``.
Calls the raise site, ``hf_materialise.preflight``, for a dataset whose size the Hub does not
report and one above the confirmation level, without ``confirm_large``, and prints each code. The
import route answers it as its error (``POST /api/v1/sources/hf``), and an import job records it as
its ``result.code``.
"""

import json
import os
import sys

from cryptography.fernet import Fernet

# Placeholder settings for IMPORTING miDataworks (never to connect), as scripts/snapshot_openapi.py.
os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
sys.path.insert(0, sys.argv[1])

from src.core.errors import AppError
from src.services.sources.hf_materialise import preflight

found = []
for expected in (None, 10):
    try:
        preflight(expected, confirm_large=False, confirm_bytes=1, free=10**12)
    except AppError as exc:
        found.append([exc.code, exc.status_code])
print(json.dumps(found))
