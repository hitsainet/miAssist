"""miDataworks: never expose a source imported with a credential (OVN-miassist-core-32; miDataworks
review OR3-022-1, 2026-11-16).

miAssist is the open endpoint (M11). miDataworks shares every imported source with every caller,
however it was imported, so a source the operator imported with a Hugging Face token (private or
gated data) would be readable through miAssist. Core therefore screens every miDataworks call:

- a source is SHOWABLE only when its ``token_tier`` is ``none`` (or ``anonymous``) and it is not
  gated; any other tier (``stored``, ``per_import``), and a tier that is missing, null or unknown,
  is not (fail closed);
- BEFORE sending, every source a call names (a ``/sources/{id}/...`` path, or any ``*source_id`` /
  ``*source_ids`` field in the body or query: a build or version input) is read with
  ``midataworks.get_source`` and must be showable, else ``source_needs_operator`` and nothing is
  sent; a source that cannot be read is refused too (``source_unchecked``);
- a VERSION is used (003's detector-set send; 004's check, publish and a build that adopts an
  existing version) only when every source its lineage reaches is showable
  (``check_version_sources``: the manifest's ``sources`` and ``/lineage``'s ``rule_sources``; R3
  review fix OR3-int-1, 2026-11-16); an unreadable lineage is refused (``source_unchecked``);
- AFTER the answer: the source list (``GET /api/v1/sources``) drops every item that is not
  showable; a single source answer (``/api/v1/sources/{id}``) that is not showable is refused; any
  other answer that embeds a source record (a mapping with a ``token_tier`` key) drops it from a
  list, or is refused.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final

from miassist.errors import MiAssistError

if TYPE_CHECKING:
    from miassist.adapters.base import AppAnswer, AppClient, Resource, Route

#: The tiers of a source imported without any credential (miDataworks ``TokenTier.NONE``;
#: ``anonymous`` is accepted as a synonym should a release spell it so).
SHOWABLE_TIERS: Final = frozenset({"none", "anonymous"})
#: ``gated`` values (miDataworks stores the Hub's value lower-cased) that mean "not gated".
NOT_GATED: Final = (None, "false", False)
SOURCES: Final = "/api/v1/sources"
_ONE_SOURCE: Final = re.compile(r"^/api/v1/sources/\{([a-z_]+)\}")
GET_SOURCE: Final = "midataworks.get_source"


def showable(source: Any) -> bool:
    if not isinstance(source, Mapping):
        return False
    tier = source.get("token_tier")
    if not (isinstance(tier, str) and tier.lower() in SHOWABLE_TIERS):
        return False
    # R3 review fix (OR3-001-6), 2026-11-16: a missing ``gated`` is unknown, like a missing tier
    # (miDataworks always sends the key); and only the exact not-gated values count (``0`` is not)
    if "gated" not in source:
        return False
    gated = source["gated"]
    return gated is None or gated is False or gated == "false"  # NOT_GATED, so 0 never counts


def _refused() -> MiAssistError:
    return MiAssistError(
        "source_needs_operator",
        "this miDataworks source was imported with the operator's credential, so miAssist does "
        "not show or use it",
        fix="the operator works with it in miDataworks; import a public dataset to use one here",
    )


def _key_form(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _unchecked(key: object) -> MiAssistError:
    return MiAssistError(
        "source_unchecked",
        f"miAssist could not read which miDataworks source {key!s} names, so it does not send it",
        fix="name one source by its id (a string), or a list of ids under a *_source_ids field",
    )


def named_source_ids(node: Any) -> list[str]:
    """Every source id a request names: any ``*source_id`` (a string) or ``*source_ids`` (a list
    of strings) field, at any depth.

    R3 review fix (OR3-001-6), 2026-11-16: a value under such a key in any other shape (a list
    under ``*source_id``, which a repeated query parameter becomes; a string under
    ``*source_ids``; a non-string id) is refused (``source_unchecked``), never skipped. ``None``
    names no source."""
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            form = _key_form(key)
            if form.endswith("sourceid"):
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise _unchecked(key)
                found.append(value)
            elif form.endswith("sourceids"):
                if value is None:
                    continue
                if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                    raise _unchecked(key)
                found += value
            else:
                found += named_source_ids(value)
    elif isinstance(node, list):
        for item in node:
            found += named_source_ids(item)
    return found


def path_source_id(route: Route, path_params: Mapping[str, Any] | None) -> str | None:
    match = _ONE_SOURCE.match(route.path)
    if match is None:
        return None
    value = (path_params or {}).get(match.group(1))
    return None if value is None else str(value)


async def check_named_sources(
    client: AppClient,
    route: Route,
    path_params: Mapping[str, Any] | None,
    params: Mapping[str, Any] | None,
    body: Any,
) -> AppAnswer | None:
    """Read every source the call names; refuse unless each is showable. Returns an
    ``Unavailable`` to pass back when the app stopped answering, else ``None``."""
    if route.id == GET_SOURCE:
        return None  # its own answer is screened
    ids = named_source_ids(body) + named_source_ids(dict(params or {}))
    one = path_source_id(route, path_params)
    if one is not None:
        ids.insert(0, one)
    return await check_sources(client, ids)


async def check_sources(client: AppClient, source_ids: Iterable[str]) -> AppAnswer | None:
    """Read each source with ``midataworks.get_source``; refuse unless each is showable
    (``source_needs_operator``), or when one cannot be read (``source_unchecked``). Returns an
    ``Unavailable`` to pass back when the app stopped answering, else ``None``."""
    from miassist.adapters.base import Resource, Unavailable

    registry = client.guards.registry
    for source_id in dict.fromkeys(source_ids):
        answer = await client.call(registry.get(GET_SOURCE), path_params={"source_id": source_id})
        if isinstance(answer, Unavailable):
            return answer
        if not isinstance(answer, Resource):
            raise MiAssistError(
                "source_unchecked",
                "miAssist could not read that miDataworks source, so it does not use it",
                fix="check the source id; miAssist uses a source only after reading how it was "
                "imported",
            )
        if not showable(answer.body):
            raise _refused()
    return None


#: How many versions a lineage walk reads at most before it stops (fail closed).
LINEAGE_MAX_VERSIONS: Final = 64
GET_MANIFEST: Final = "midataworks.get_version_manifest"
GET_LINEAGE: Final = "midataworks.get_version_lineage"


def _lineage_unchecked() -> MiAssistError:
    return MiAssistError(
        "source_unchecked",
        "miAssist could not read which miDataworks sources this version was built from, so it "
        "does not use it",
        fix="the operator works with it in miDataworks, or build a version here from a public "
        "dataset",
    )


def _ids_in(items: Any, key: str, kinds: frozenset[str] | None = None) -> list[str]:
    """``item[key]`` of each item (of ``kinds`` when given); fail closed on any other shape."""
    if not isinstance(items, list):
        raise _lineage_unchecked()
    found: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise _lineage_unchecked()
        if kinds is not None and item.get("kind") not in kinds:
            continue
        value = item.get(key)
        if not (isinstance(value, str) and value):
            raise _lineage_unchecked()
        found.append(value)
    return found


async def _read_body(client: AppClient, route_id: str, version_id: str) -> Any:
    from miassist.adapters.base import Resource, Unavailable

    answer = await client.call(
        client.guards.registry.get(route_id), path_params={"version_id": version_id}
    )
    if isinstance(answer, Unavailable):
        return answer
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        raise _lineage_unchecked()
    return answer.body


async def check_version_sources(client: AppClient, version_id: str) -> AppAnswer | None:
    """R3 review fix (OR3-int-1), 2026-11-16 (OVN-miassist-int-23): a version is used only when
    every source in its lineage is showable, read from what miDataworks records as the lineage,
    never from ``VersionOut.inputs`` alone (which holds the build request's inputs only):

    - ``GET /versions/{id}/manifest``: ``sources`` (every source reached through the inputs AND
      the ``rule_source`` ancestors, transitively; ``version_finalize.py:572-645`` @ dcec0cb) and
      ``inputs`` (``kind: source``);
    - ``GET /versions/{id}/lineage``: ``inputs`` (``kind: version``) and ``rule_sources`` (the
      versions a derived rule set was learned from; ``lineage_service.py:129-190``), each walked
      the same way, at most ``LINEAGE_MAX_VERSIONS`` versions.

    Every source found is screened with Core's rule (``check_sources``: ``source_needs_operator``).
    Fails closed (``source_unchecked``): an unreadable manifest or lineage, a missing or empty
    ``sources``, an item of another shape, more than the cap. Returns an ``Unavailable`` to pass
    back when the app stopped answering, else ``None``."""
    from miassist.adapters.base import Unavailable

    sources: list[str] = []
    seen: set[str] = {version_id}
    queue = [version_id]
    while queue:
        current = queue.pop()
        manifest = await _read_body(client, GET_MANIFEST, current)
        if isinstance(manifest, Unavailable):
            return manifest
        reached = _ids_in(manifest.get("sources"), "source_id")
        if not reached:
            raise _lineage_unchecked()
        sources += reached + _ids_in(manifest.get("inputs"), "source_id", frozenset({"source"}))
        lineage = await _read_body(client, GET_LINEAGE, current)
        if isinstance(lineage, Unavailable):
            return lineage
        above = _ids_in(lineage.get("inputs"), "version_id", frozenset({"version"}))
        above += _ids_in(lineage.get("rule_sources"), "version_id")
        for parent in above:
            if parent in seen:
                continue
            seen.add(parent)
            if len(seen) > LINEAGE_MAX_VERSIONS:
                raise _lineage_unchecked()
            queue.append(parent)
    return await check_sources(client, sources)


def _strip(node: Any) -> Any:
    """Drop every embedded source record that is not showable from lists; refuse one held
    anywhere else."""
    if isinstance(node, Mapping):
        if "token_tier" in node and not showable(node):
            raise _refused()
        return {k: _strip(v) for k, v in node.items()}
    if isinstance(node, list):
        return [
            _strip(item)
            for item in node
            if not (isinstance(item, Mapping) and "token_tier" in item and not showable(item))
        ]
    return node


def _list_items(body: Any) -> tuple[Any, str | None]:
    if isinstance(body, list):
        return body, None
    if isinstance(body, Mapping):
        for key in ("items", "sources", "data"):
            if isinstance(body.get(key), list):
                return body[key], key
    return None, None


def screen_answer(route: Route, answer: AppAnswer) -> AppAnswer:
    from miassist.adapters.base import Resource

    if not isinstance(answer, Resource):
        return answer
    body = answer.body
    if route.method == "GET" and route.path == SOURCES:
        items, key = _list_items(body)
        if items is None:
            raise MiAssistError(
                "source_unchecked",
                "miDataworks' source list was not in a shape miAssist reads, so it shows none",
                fix="the app's version may differ from the one miAssist was built against",
            )
        kept = [_strip(item) for item in items if showable(item)]
        body = kept if key is None else {**body, key: kept}
        return _resource(answer, body)
    if route.method == "GET" and _ONE_SOURCE.fullmatch(route.path) and not showable(body):
        raise _refused()
    return _resource(answer, _strip(body))


def _resource(answer: Resource, body: Any) -> Resource:
    from miassist.adapters.base import Resource

    return Resource(answer.app, answer.status, body)
