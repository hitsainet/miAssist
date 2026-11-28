"""The ONE id-filter rule for recorded cassettes (001 FR-31; A22, A37, R2M-7; FTID §8.3).

Both Core's recorder (``scripts/record_cassettes.py``) and 002's recording proxy import these three
objects; 002 asserts ``is`` identity with them, and neither defines a rule of its own.

- ``AllowedSet``: the values a recording may carry. It starts from the fixture list
  (``eval/fixtures.yaml``: the ``evalfx-`` prefix, listed ids, the public repositories by name).
  ``check_request(profile, request)`` refuses, BEFORE the request is sent, a value outside the set
  in every path parameter and in every query or body field (at any depth) named ``id``, ``*_id``,
  ``*_ids`` (each element), ``name``, ``key`` or ``repo_id``, or added by the route's profile. On a
  route the profile marks ``creates``, a top-level body ``name`` or ``key`` is a new value and is
  added instead. ``grow(answer)`` adds the ids a ``creates`` route's answer carries.
- ``filter_list(answer, allowed)``: an answer with every list item that names a non-fixture value
  removed.
- ``final_scan(cassette, allowed)``: every finding left in a finished cassette (the recorder refuses
  to write on any).

This module imports nothing from ``miassist`` (``tests/unit/test_fixture_filter.py`` pins it).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["AllowedSet", "FixtureRefused", "RouteProfile", "filter_list", "final_scan"]

DEFAULT_PREFIX = "evalfx-"
_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def identifying(name: str, extra: Iterable[str] = ()) -> bool:
    """Whether a field named ``name`` carries an identifier the rule checks."""
    return (
        name in ("id", "name", "key", "repo_id")
        or name.endswith("_id")
        or name.endswith("_ids")
        or name in set(extra)
    )


class FixtureRefused(ValueError):
    """A request or cassette carries a value that is not fixture data."""

    def __init__(self, where: str, value: Any) -> None:
        super().__init__(f"not fixture data at {where}")
        self.where = where
        self.value = value


@dataclass(frozen=True)
class RouteProfile:
    """A route as the rule sees it: its path template, whether it creates, extra fields."""

    template: str
    creates: bool = False
    fields: frozenset[str] = frozenset()

    def path_params(self, path: str) -> dict[str, str] | None:
        parts = _PARAM.split(self.template)
        pattern = "".join(
            re.escape(part) if i % 2 == 0 else f"(?P<{part}>[^/]+)" for i, part in enumerate(parts)
        )
        match = re.fullmatch(pattern, path)
        return match.groupdict() if match else None


def _walk(node: Any, extra: Iterable[str], where: str) -> Iterator[tuple[str, Any]]:
    """``(where, value)`` for every identifying field's value(s) at any depth."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            here = f"{where}.{key}"
            if identifying(str(key), extra):
                if isinstance(value, list):
                    for i, item in enumerate(value):
                        if not isinstance(item, (Mapping, list)):
                            yield f"{here}[{i}]", item
                elif not isinstance(value, Mapping):
                    yield here, value
            yield from _walk(value, extra, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk(item, extra, f"{where}[{i}]")


@dataclass
class AllowedSet:
    """The values a recording may carry: the fixture list plus what this run created."""

    prefix: str = DEFAULT_PREFIX
    ids: set[str] = field(default_factory=set)
    repositories: set[str] = field(default_factory=set)
    created: set[str] = field(default_factory=set)

    @classmethod
    def from_fixtures(cls, path: Path) -> AllowedSet:
        """From 002's ``eval/fixtures.yaml`` (``prefix``, ``ids``, ``public_repositories``); an
        absent file allows only the prefix."""
        if not path.is_file():
            return cls()
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            prefix=str(data.get("prefix", DEFAULT_PREFIX)),
            ids={str(i) for i in data.get("ids", [])},
            repositories={str(r) for r in data.get("public_repositories", [])},
        )

    def allows(self, value: Any) -> bool:
        if value is None or isinstance(value, bool):
            return True
        text = str(value)
        return (
            text.startswith(self.prefix)
            or text in self.ids
            or text in self.repositories
            or text in self.created
        )

    def check_request(self, profile: RouteProfile, request: Mapping[str, Any]) -> None:
        """Refuse a request carrying a non-fixture value; grow on a ``creates`` route's body."""
        params = profile.path_params(str(request.get("path", "")))
        if params is None:
            raise FixtureRefused("path", request.get("path"))
        for name, value in params.items():
            if not self.allows(value):
                raise FixtureRefused(f"path.{name}", value)
        for where, value in _walk(request.get("query") or {}, profile.fields, "query"):
            if not self.allows(value):
                raise FixtureRefused(where, value)
        body = request.get("body")
        new: set[str] = set()
        if profile.creates and isinstance(body, Mapping):
            new = {str(body[k]) for k in ("name", "key") if isinstance(body.get(k), str)}
        for where, value in _walk(body, profile.fields, "body"):
            if where in ("body.name", "body.key") and str(value) in new:
                continue
            if not self.allows(value):
                raise FixtureRefused(where, value)
        self.created |= new

    def grow(self, answer: Any) -> None:
        """Add the identifiers a ``creates`` route's own answer carries."""
        for _, value in _walk(answer, (), "answer"):
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                self.created.add(str(value))


def _item_ok(item: Any, allowed: AllowedSet) -> bool:
    if not isinstance(item, Mapping):
        return True
    return all(allowed.allows(v) for _, v in _walk(item, (), "item"))


def filter_list(answer: Any, allowed: AllowedSet) -> Any:
    """The answer with every list item that names a non-fixture value removed, at any depth."""
    if isinstance(answer, list):
        return [filter_list(i, allowed) for i in answer if _item_ok(i, allowed)]
    if isinstance(answer, Mapping):
        return {k: filter_list(v, allowed) for k, v in answer.items()}
    return answer


def final_scan(cassette: Mapping[str, Any], allowed: AllowedSet) -> list[str]:
    """Every non-fixture value left in a finished cassette (path, query, body, answer)."""
    findings: list[str] = []
    for record in cassette.get("records", []):
        request = record.get("request", {})
        seq = record.get("seq")
        profile = RouteProfile(str(request.get("route", "")))
        params = profile.path_params(str(request.get("path", ""))) or {}
        for name, value in params.items():
            if not allowed.allows(value):
                findings.append(f"records[{seq}].request.path.{name}")
        for part in ("query", "body"):
            for where, value in _walk(request.get(part), (), part):
                if not allowed.allows(value):
                    findings.append(f"records[{seq}].request.{where}")
        for where, value in _walk(record.get("answer", {}).get("body"), (), "answer"):
            if not allowed.allows(value):
                findings.append(f"records[{seq}].{where}")
    return findings
