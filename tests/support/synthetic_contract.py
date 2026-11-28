"""A small answer contract in miServer's layout, for the reader's tests (ENH-013 006, FTASKS 1.5).

Until a sibling's contract is vendored (006-1), the reader, its strict form and the evaluation
reader are proven against this document. Its definitions are cut down from miServer's contract at
``feat/044-typed-answers`` ``a8ff9281`` (``ProbeSummary`` and ``ProbeListItem``, the ``ApiResponse``
and ``PageOf`` envelopes, ``ApprovalRead``'s open ``summary`` map, a ``__history`` result form), plus
the forms a reader must handle that miServer's lacks today: a definition that refers to itself, a
route key holding ``~``, and an external ``$id``.

Standard library only: ``eval/tests/unit/test_contract_reader_parity.py`` loads it by path.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

APP = "miserver"
ID = "https://hitsai.net/schemas/miserver-answers-v1.json"
EXTERNAL = "https://raw.githubusercontent.com/hitsainet/miStudio/main/docs/schemas/cluster-definition-v1.json"

SUMMARY_PROPS: dict[str, Any] = {
    "id": {"type": "string"},
    "name": {"type": "string"},
    "derived_from": {"anyOf": [{"type": "string"}, {"type": "null"}]},
}
DEFS: dict[str, Any] = {
    "ErrorDetails": {
        "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
        "required": ["code", "message"],
        "type": "object",
    },
    "ProbeSummary": {
        "description": "One probe as an import answers it",
        "properties": SUMMARY_PROPS,
        "required": ["id", "name", "derived_from"],
        "type": "object",
    },
    "ProbeListItem": {
        "properties": {**SUMMARY_PROPS, "results_total": {"type": "integer"}},
        "required": ["id", "name", "derived_from", "results_total"],
        "type": "object",
    },
    "PageOf_ProbeListItem_": {
        "properties": {
            "success": {"type": "boolean"},
            "data": {
                "anyOf": [
                    {"items": {"$ref": "#/$defs/ProbeListItem"}, "type": "array"},
                    {"type": "null"},
                ]
            },
            "error": {"anyOf": [{"$ref": "#/$defs/ErrorDetails"}, {"type": "null"}]},
            "meta": {"anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}]},
        },
        "required": ["success", "data", "error", "meta"],
        "type": "object",
    },
    "ProbeStatus": {
        "properties": {
            "armed": {"type": "integer"},
            "served_weights": {"enum": ["base", "attached"], "type": "string"},
        },
        "required": ["armed", "served_weights"],
        "type": "object",
    },
    "ApiResponse_ProbeStatus_": {
        "properties": {
            "success": {"type": "boolean"},
            "data": {
                "anyOf": [
                    {"$ref": "#/$defs/ProbeStatus", "description": "The status"},
                    {"type": "null"},
                ]
            },
            "error": {"anyOf": [{"$ref": "#/$defs/ErrorDetails"}, {"type": "null"}]},
        },
        "required": ["success", "data", "error"],
        "type": "object",
    },
    "ChatCompletion": {
        "properties": {
            "id": {"type": "string"},
            "object": {"const": "chat.completion", "type": "string"},
            "system_fingerprint": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["id", "object"],
        "type": "object",
    },
    "ProbeCapacity__history": {
        "properties": {"armed": {"type": "integer"}, "cards": {"type": "array"}},
        "required": ["armed", "cards"],
        "type": "object",
    },
    "ApprovalRead": {
        "properties": {
            "approval_id": {"pattern": "^apr_", "type": "string"},
            "action": {"type": "string"},
            "summary": {"additionalProperties": True, "type": "object"},
            "result": {"anyOf": [{"$ref": "#/$defs/ProbeCapacity__history"}, {"type": "null"}]},
        },
        "required": ["approval_id", "action", "summary", "result"],
        "type": "object",
    },
    "Node": {
        "properties": {
            "name": {"type": "string"},
            "children": {"items": {"$ref": "#/$defs/Node"}, "type": "array"},
        },
        "required": ["name", "children"],
        "type": "object",
    },
    "ClusterRead": {
        "properties": {"id": {"type": "string"}, "definition": {"$ref": EXTERNAL}},
        "required": ["id", "definition"],
        "type": "object",
    },
    "RefusalEnvelope": {
        "properties": {
            "success": {"const": False},
            "data": {"type": "null"},
            "error": {"$ref": "#/$defs/ErrorDetails"},
        },
        "required": ["success", "data", "error"],
        "type": "object",
    },
}
RESPONSES: dict[str, Any] = {
    "GET /api/probes/status": {"200": {"$ref": "#/$defs/ApiResponse_ProbeStatus_"}},
    "GET /api/probes": {"200": {"$ref": "#/$defs/PageOf_ProbeListItem_"}},
    "GET /api/probes/{probe_id}/runs": {
        "200": {"items": {"$ref": "#/$defs/ProbeListItem"}, "type": "array"}
    },
    "POST /api/probes/import": {"201": {"$ref": "#/$defs/ProbeSummary"}},
    "POST /v1/chat/completions": {
        "200": {"$ref": "#/$defs/ChatCompletion"},
        "x-variants": {"text/event-stream": "stream=true answers Server-Sent Events"},
    },
    "GET /api/approvals/{approval_id}": {
        "200": {"$ref": "#/$defs/ApprovalRead"},
        "x-approval-action": "capacity_measure",
    },
    "GET /api/tree": {"200": {"$ref": "#/$defs/Node"}},
    "GET /api/clusters/{cluster_id}": {"200": {"$ref": "#/$defs/ClusterRead"}},
    "GET /api/a~b/{c}": {"200": {"$ref": "#/$defs/ErrorDetails"}},
}


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def document(app: str = APP, **changes: Any) -> dict[str, Any]:
    """The synthetic contract for ``app`` (``changes`` replace top-level keys), digested by the
    producers' rule so a reader's ``load`` accepts it."""
    doc: dict[str, Any] = {
        "$defs": copy.deepcopy(DEFS),
        "$id": ID.replace("miserver", app),
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "kind": f"{app}.answer-contract/v1",
        "responses": copy.deepcopy(RESPONSES),
        "excluded": {
            "GET /api/health/metrics/prometheus": {"media_type": "text/plain", "reason": "text"}
        },
        "errors": {"management": {"$ref": "#/$defs/RefusalEnvelope"}},
        "external": {EXTERNAL: {"file": "docs/schemas/cluster-definition-v1.json", "sha256": "0"}},
        "coverage": {"excluded": 1, "typed": len(RESPONSES), "unions": 0, "untyped": 0},
        "revision": 1,
        "title": f"{app} answers (synthetic)",
    }
    doc.update(changes)
    body = {k: v for k, v in doc.items() if k not in ("revision", "content_sha256")}
    doc["content_sha256"] = hashlib.sha256(render(body).encode("utf-8")).hexdigest()
    return doc
