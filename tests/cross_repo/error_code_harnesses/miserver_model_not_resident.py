"""miServer's OpenAI-compatible "model not resident" refusal (ENH-013 006, FR-006.7).

Run in miServer's own interpreter on a ``git archive``: ``python -I -B <this> <archive root>``.
Calls the function that builds the refusal, ``model_not_resident_error``, and prints the answer's
``error.code`` and HTTP status.
"""

import json
import sys

sys.path.insert(0, sys.argv[1])

from miserver.api.routes.openai.errors import model_not_resident_error

answer = model_not_resident_error("evalfx-model", None)
body = json.loads(bytes(answer.body))
print(json.dumps([[body["error"]["code"], answer.status_code]]))
