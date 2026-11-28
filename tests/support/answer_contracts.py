"""Sibling answer shapes from their published contracts (ENH-013 feature 006; FTDD §6.2, FTID §3.1).

Each sibling publishes ``docs/schemas/<app>-answers-v1.json``: every typed answer of its routes,
keyed ``responses["<METHOD> <path>"]["<status>"]``, with ``$defs``, ``excluded`` (routes that answer
no JSON), ``errors`` (the error envelopes) and ``external`` (document schemas it references by
``$id``). miAssist copies it byte-identical (MA1) and reads that app's answer shapes from it once the
app's state here is ``vendored`` (MA4). Until then the app is ``hand``: its shapes are still
``tests/fixtures/openapi/responses.json`` and the OpenAPI snapshot (``response_shapes``).

- ``ANSWER_SOURCES`` is the per-app state. Each 006 push flips one app.
- ``Contract`` reads one document: an entry, its ``$ref`` form (for ``response_shapes.check`` with
  ``resources``), its inlined form (for ``example``, ``fill`` and the checks the fakes run), the
  error envelopes and the external ``$id``s, each resolved to an open object (AT3).
- ``strict_form`` is MA2: objects with named properties closed and maps left open, by PRE-006's
  ``response_shapes.strict`` (the one closing rule, so a fake is held to one standard whatever
  the source of its shape); ``required`` is the contract's own and is never widened; a
  history-form definition (``<Name>__history``, miServer TD14) is read with no ``required``.

The module imports nothing from ``miassist`` or ``tests`` at import time (``response_shapes`` only
inside ``strict_form`` and ``check``), so ``eval/tests/unit/test_contract_reader_parity.py`` can
load it by path in the evaluation environment, which holds no server package.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

ROOT = Path(__file__).resolve().parents[2]
APPS: Final = ("miserver", "midataworks", "miworkbench", "miforge")
State = Literal["hand", "vendored"]

#: Each app's answer source (MA4). 006-1 flips miServer, 006-2 miDataworks, 006-3 miWorkbench and
#: 006-4 miForge; ``tests/contract/test_answer_contracts.py`` holds each state to its files.
ANSWER_SOURCES: dict[str, State] = {
    "miserver": "vendored",
    "midataworks": "hand",
    "miworkbench": "hand",
    "miforge": "hand",
}
#: The ``errors`` envelope that answers a refusal of each app's route (FR-006.7, MA3), by path:
#: miServer answers ``/v1/`` (OpenAI-compatible) routes with ``openai`` and every other route with
#: ``management``; miDataworks names one, ``app``. miWorkbench and miForge are named when their
#: contracts are vendored (006-3, 006-4), from the ``errors`` keys they publish.
ERROR_ENVELOPES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "miserver": (("/v1/", "openai"), ("/", "management")),
    "midataworks": (("/", "app"),),
}
#: The vendored file of each app (MA1). miForge's name is confirmed when its chain sets it (006-4).
FILES: Final = {app: f"{app}-answers-v1.json" for app in APPS}
#: The producer's digest rule (miServer ``contract_tools.content_digest``, FR-044.18): sha256 of the
#: rendered document without these two keys. Restated here; no sibling code is imported.
UNDIGESTED: Final = ("revision", "content_sha256")
DEFS: Final = "#/$defs/"
#: A ``responses`` entry's statuses; its other keys (``x-approval-action``, ``x-variants``) are notes.
STATUS: Final = re.compile(r"^[1-5][0-9][0-9]$")
#: A definition that is a recorded result's history form (miServer TD14): an old approval's
#: ``result`` was stored when the model had fewer fields, so none of its fields is required.
HISTORY: Final = re.compile(r"__history$")
#: An external document schema, read as an open object (AT3): miAssist vendors none of them.
OPEN: Final[dict[str, Any]] = {"type": "object"}


class ContractError(ValueError):
    """A vendored copy that is not a contract, or not the bytes its producer digested."""


#: A vendored contract's row in ``docs/schemas/README.md`` says "copied at <commit>, revision <n>".
COPIED: Final = re.compile(r"copied at ([0-9a-f]{7,40}), revision (\d+)")


def readme_row(file: str, readme: Path | None = None) -> str:
    text = (readme or schemas_dir() / "README.md").read_text()
    rows = [line for line in text.splitlines() if line.startswith(f"| `{file}` |")]
    if len(rows) != 1:
        raise ContractError(f"docs/schemas/README.md has {len(rows)} rows for {file}")
    return rows[0]


def copied(row: str) -> tuple[str, int]:
    """``(commit, revision)`` a README row names."""
    found = COPIED.search(row)
    if not found:
        raise ContractError(f"the row does not say 'copied at <commit>, revision <n>': {row}")
    return found.group(1), int(found.group(2))


def schemas_dir() -> Path:
    return Path(os.environ.get("MIASSIST_ANSWER_CONTRACTS_DIR", ROOT / "docs" / "schemas"))


def path(app: str) -> Path:
    return schemas_dir() / FILES[app]


def vendored(app: str) -> bool:
    return ANSWER_SOURCES.get(app) == "vendored"


def render(doc: Mapping[str, Any]) -> str:
    """The producer's committed byte form (miServer ``contract_tools.render``)."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def content_digest(doc: Mapping[str, Any]) -> str:
    body = {k: v for k, v in doc.items() if k not in UNDIGESTED}
    return hashlib.sha256(render(body).encode("utf-8")).hexdigest()


def key(method: str, template: str) -> str:
    return f"{method.upper()} {template}"


def escape(part: str) -> str:
    """One JSON Pointer reference part (RFC 6901): ``~`` as ``~0``, ``/`` as ``~1``."""
    return part.replace("~", "~0").replace("/", "~1")


def checked(app: str, doc: Any, where: str = "") -> dict[str, Any]:
    """``doc`` if it is ``app``'s contract with the digest its producer wrote, else ContractError."""
    where = where or app
    if not isinstance(doc, dict):
        raise ContractError(f"{where}: not a JSON object")
    kind = f"{app}.answer-contract/v1"
    if doc.get("kind") != kind:
        raise ContractError(f"{where}: kind {doc.get('kind')!r}, expected {kind!r}")
    for name, kind_of in (("$id", str), ("responses", dict), ("$defs", dict)):
        if not isinstance(doc.get(name), kind_of):
            raise ContractError(f"{where}: {name} is not a {kind_of.__name__}")
    digest = content_digest(doc)
    if doc.get("content_sha256") != digest:
        raise ContractError(
            f"{where}: content_sha256 {doc.get('content_sha256')!r} but the content digests to "
            f"{digest!r}: the copy was edited or damaged (copy it again, never edit it)"
        )
    return doc


def history_open(node: Any) -> Any:
    """``node`` with no ``required`` anywhere in it: a history-form definition as it is read."""
    if isinstance(node, list):
        return [history_open(v) for v in node]
    if not isinstance(node, dict):
        return node
    return {
        k: history_open(v) for k, v in node.items() if not (k == "required" and isinstance(v, list))
    }


def strict_form(schema: Any) -> Any:
    """MA2's strict form of an inlined contract schema (FTDD §6.2 step 3) by PRE-006's closing rule
    (``response_shapes.strict``), so a fake is held to one standard whatever its shape's source.
    ``required`` is the contract's own and is never widened. The history rule is applied where a
    definition is read (``Contract.definition``), since an inlined schema no longer names it."""
    from tests.support import response_shapes as rs

    return rs.strict(schema)


class Contract:
    """One app's answer contract."""

    def __init__(self, app: str, doc: Mapping[str, Any]) -> None:
        self.app = app
        self.doc: dict[str, Any] = dict(doc)
        self.id: str = str(self.doc["$id"])
        self.defs: dict[str, Any] = dict(self.doc.get("$defs") or {})
        self.responses: dict[str, Any] = dict(self.doc.get("responses") or {})
        self.excluded: dict[str, Any] = dict(self.doc.get("excluded") or {})
        self.errors: dict[str, Any] = dict(self.doc.get("errors") or {})
        self.external: dict[str, Any] = dict(self.doc.get("external") or {})

    # -- lookups ------------------------------------------------------------------------------

    def statuses(self, method: str, template: str) -> list[str]:
        return sorted(s for s in self.responses.get(key(method, template), {}) if STATUS.match(s))

    def entry(self, method: str, template: str, status: int | str) -> Any:
        """The contract's raw schema, or None when the route is ``excluded`` (it answers no JSON:
        a fake answering it with JSON is inventing it) or the contract has no such answer."""
        route = key(method, template)
        if route in self.excluded:
            return None
        found = self.responses.get(route, {})
        status = str(status)
        return found.get(status) if STATUS.match(status) else None

    def schema_for(self, method: str, template: str, status: int | str) -> dict[str, Any] | None:
        """The answer as a ``$ref`` into the contract, for ``response_shapes.check`` with
        ``resources=self.resources()``; None as ``entry``."""
        if self.entry(method, template, status) is None:
            return None
        pointer = f"/responses/{escape(key(method, template))}/{status}"
        return {"$ref": f"{self.id}#{pointer}"}

    def resources(self) -> dict[str, Any]:
        """The documents a ``$ref`` form resolves through: this contract under its ``$id`` (history
        rule applied; ``check`` closes it) and each external ``$id`` as an open object (AT3)."""
        found: dict[str, Any] = {uri: dict(OPEN) for uri in self.external}
        found[self.id] = {**self.doc, "$defs": {n: self.definition(n) for n in self.defs}}
        return found

    # -- the inlined form ---------------------------------------------------------------------

    def inline(self, node: Any) -> Any:
        """``node`` with every ``#/$defs/`` reference inlined (siblings of a ``$ref`` merged over
        its target, as ``scripts/snapshot_shapes.resolve`` and ``eval``'s reader do) and every
        external reference an open object. A definition that refers back to itself keeps a local
        ``$ref``, and the definitions it needs are carried under the result's own ``$defs``."""
        carried: dict[str, Any] = {}
        out = self._inline(node, (), carried)
        if carried and isinstance(out, dict):
            out = {**out, "$defs": {**out.get("$defs", {}), **carried}}
        return out

    def _inline(self, node: Any, stack: tuple[str, ...], carried: dict[str, Any]) -> Any:
        if isinstance(node, list):
            return [self._inline(v, stack, carried) for v in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str):
            siblings = {k: self._inline(v, stack, carried) for k, v in node.items() if k != "$ref"}
            if ref.startswith(DEFS):
                name = ref[len(DEFS) :]
                if name not in self.defs:
                    raise ContractError(f"{self.app}: {ref} names no definition")
                if name in stack:
                    if name not in carried:
                        carried[name] = {}
                        carried[name] = self._inline(self.definition(name), (name,), carried)
                    return {"$ref": ref, **siblings}
                target = self._inline(self.definition(name), (*stack, name), carried)
                return {**target, **siblings} if isinstance(target, dict) else target
            if ref in self.external:
                return {**OPEN, **siblings}
            raise ContractError(f"{self.app}: {ref} is neither a definition nor an external $id")
        return {k: self._inline(v, stack, carried) for k, v in node.items()}

    def definition(self, name: str) -> Any:
        """``$defs[name]`` as it is read: a history-form definition keeps no ``required``."""
        target = self.defs[name]
        return history_open(target) if HISTORY.search(name) else target

    def inlined(self, method: str, template: str, status: int | str) -> Any:
        """The answer's schema inlined, before the strict form (what ``eval`` reads, AT2)."""
        found = self.entry(method, template, status)
        return None if found is None else self.inline(found)

    def resolved(self, method: str, template: str, status: int | str) -> Any:
        """The answer's schema inlined and in its strict form: what a fake is checked against and
        what ``example`` and ``fill`` build from."""
        found = self.inlined(method, template, status)
        return None if found is None else strict_form(found)

    def error_schema(self, which: str) -> Any:
        """``errors[which]`` (``management``, ``openai``, ``app``...), inlined and strict."""
        if which not in self.errors:
            raise KeyError(f"{self.app}'s contract names no {which!r} error envelope")
        return strict_form(self.inline(self.errors[which]))


#: The loaded contracts, by app (tests put synthetic ones here with ``monkeypatch.setitem``).
LOADED: dict[str, Contract] = {}


def load(app: str) -> dict[str, Any]:
    """``app``'s vendored copy, its kind and digest checked."""
    file = path(app)
    if not file.is_file():
        raise ContractError(f"{app} is {ANSWER_SOURCES.get(app)!r} but {file} does not exist")
    return checked(app, json.loads(file.read_text()), str(file))


def contract(app: str) -> Contract:
    if app not in LOADED:
        LOADED[app] = Contract(app, load(app))
    return LOADED[app]


def schema_for(app: str, method: str, template: str, status: int | str) -> dict[str, Any] | None:
    return contract(app).schema_for(method, template, status)


def resolved(app: str, method: str, template: str, status: int | str) -> Any:
    return contract(app).resolved(method, template, status)


def error_schema(app: str, which: str) -> Any:
    return contract(app).error_schema(which)


def envelope_for(app: str, template: str) -> str:
    """Which ``errors`` envelope answers a refusal of ``template`` (``ERROR_ENVELOPES``)."""
    for prefix, which in ERROR_ENVELOPES.get(app, ()):
        if template.startswith(prefix):
            return which
    raise KeyError(f"no error envelope is named for {app} {template} (ERROR_ENVELOPES)")


def refusal(app: str, method: str, template: str, status: int | str) -> Any:
    """The shape of a 4xx or 5xx answer: the route's own entry where the contract has one, else
    the envelope ``envelope_for`` names."""
    found = contract(app).resolved(method, template, status)
    return found if found is not None else error_schema(app, envelope_for(app, template))


def check(app: str, method: str, template: str, status: int | str, value: Any) -> list[str]:
    """``value`` checked through the contract's ``$ref`` form and registry (no inlining)."""
    from tests.support import response_shapes as rs

    found = schema_for(app, method, template, status)
    if found is None:
        return [f"$: {app}'s contract has no {status} answer for {key(method, template)}"]
    return rs.check(found, value, resources=contract(app).resources())
