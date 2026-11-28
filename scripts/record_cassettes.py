"""Record Core's route cassettes from a running app (001 FR-31; A22, A37, M14; FTASKS 4.5).

    python -m scripts.record_cassettes --app miforge --base-url http://<LAN host> [--fixtures eval/fixtures.yaml]

OPERATOR-RUN, against fixture data only. Every request is vetted by the ONE id-filter rule
(``miassist_fixtures.filter``) BEFORE it is sent: a path parameter or an identifying field whose
value is neither on the fixture list nor created by this run is refused and nothing is sent. Every
list answer is filtered to fixture items; the finished cassette is re-scanned (``final_scan``) and
run through Foundation 1.7's secret scanner and a structural scan that refuses any credential-named
key holding a value (``credential_keys``; R2 review fix OR2-001-2); any finding refuses the write. A cassette is written
only under ``tests/fixtures/cassettes/private/`` (stripped from the public mirror); the operator
reviews it before it is committed to the private repository.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import re
import sys
import urllib.parse
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from miassist_fixtures.filter import (
    AllowedSet,
    FixtureRefused,
    RouteProfile,
    filter_list,
    final_scan,
)
from tests.support.cassette import (
    FORMAT,
    Cassette,
    CassetteRoot,
    strip_answer_headers,
    strip_request_headers,
)
from tests.support.secret_scan import PLACEHOLDER, SHAPES, scan_text

from miassist.adapters.base import HEADERS

#: Core's reads per app (FPRD FR-24), recorded as one cassette each: (route template, query).
CORE_READS: dict[str, list[tuple[str, dict[str, str]]]] = {
    "miworkbench": [
        ("/api/v1/models", {"page": "1", "limit": "3"}),
        ("/api/v1/saes", {"skip": "0", "limit": "3"}),
        ("/api/v1/datasets", {"page": "1", "limit": "3"}),
        ("/api/v1/probe-monitors/probes", {}),
    ],
    "miserver": [("/api/models", {}), ("/api/probes/status", {}), ("/api/clusters", {})],
    "midataworks": [
        ("/api/v1/datasets", {"page": "1", "limit": "3"}),
        ("/api/v1/versions", {"page": "1", "limit": "3"}),
    ],
    "miforge": [
        ("/api/v1/runs", {"limit": "3", "offset": "0"}),
        ("/api/v1/packs", {}),
        ("/api/v1/checkpoints", {"limit": "3"}),
    ],
}


#: Key names that carry a credential, compared after ``key_form`` (any case, separators, URL or HTML
#: escaping removed): the key IS one of these or ENDS with one (``hf_token``, ``x-api-key``,
#: ``clientSecret``, ``Proxy-Authorization``). R2 review fix (OR2-001-2), 2026-11-16.
CREDENTIAL_KEY_ENDINGS: tuple[str, ...] = (
    "token",
    "password",
    "passwd",
    "passphrase",
    "secret",
    "secrets",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "privatekey",
    # R3 review fix (OR3-001-5), 2026-11-16: secret_key, access_key (so aws_secret_access_key),
    # pwd, auth (so x-auth, oauth) and cookie, any case.
    "secretkey",
    "accesskey",
    "pwd",
    "auth",
    "cookie",
)
#: A string value that is an HTTP bearer credential, under any key (R3 review fix OR3-001-5).
BEARER_VALUE = re.compile(r"^\s*bearer\s+\S{8,}", re.IGNORECASE)
#: A bearer credential anywhere in a string (prose, a header line): the tracked-file scanner's own
#: shape, skipped on placeholders (confirmation fix C-001-4, 2026-11-16).
BEARER_IN_TEXT = SHAPES["bearer_token"]
#: Keys that NAME a header or setting whose value sits beside it under ``value`` (HAR-style
#: ``{"name": "Authorization", "value": "..."}``), compared after ``key_form`` (C-001-4).
NAME_KEYS: frozenset[str] = frozenset({"name", "key", "header", "field"})
#: Tokenizer vocabulary keys that end in "token" but hold a vocabulary entry, never a credential
#: (exact, after ``key_form``).
TOKENIZER_KEYS: frozenset[str] = frozenset(
    {"bostoken", "eostoken", "padtoken", "unktoken", "septoken", "clstoken", "masktoken"}
)


def key_form(key: object) -> str:
    """A key as compared: URL and HTML escapes undone (twice), lower case, letters and digits only."""
    text = str(key)
    for _ in range(2):
        text = html.unescape(urllib.parse.unquote_plus(text))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_credential_key(key: object) -> bool:
    form = key_form(key)
    return form not in TOKENIZER_KEYS and form.endswith(CREDENTIAL_KEY_ENDINGS)


def _holds_value(value: object) -> bool:
    """A credential key with nothing in it (None, "", False, an empty container) carries nothing."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str | list | dict):
        return len(value) > 0
    return True


def _bearer(text: str) -> bool:
    """A bearer credential: the whole value (``Bearer <8+ chars>``) or anywhere in the text."""
    if BEARER_VALUE.match(text):
        return True
    return any(not PLACEHOLDER.match(m.group(1)) for m in BEARER_IN_TEXT.finditer(text))


def _names_a_credential(name: object, item: object) -> bool:
    return isinstance(name, str) and is_credential_key(name) and _holds_value(item)


def credential_keys(value: object, where: str = "$") -> list[str]:
    """Every place in ``value`` where a credential-named key holds a value: mappings, lists, JSON
    text inside a string (also JSON text encoded again as a JSON string), and ``a=1&token=x`` query
    text inside a string; and every bearer credential in any string. Header lists count as keys:
    a ``[name, value]`` pair and a ``{"name": ..., "value": ...}`` mapping (confirmation fix
    C-001-4, 2026-11-16). Paths only, never values.
    """
    found: list[str] = []
    if isinstance(value, Mapping):
        named_by = [k for k in value if key_form(k) in NAME_KEYS]
        for key, item in value.items():
            here = f"{where}.{key}"
            if is_credential_key(key) and _holds_value(item):
                found.append(here)
            if key_form(key) == "value" and any(
                _names_a_credential(value[k], item) for k in named_by
            ):
                found.append(here)
            found += credential_keys(item, here)
    elif isinstance(value, list):
        if len(value) == 2 and _names_a_credential(value[0], value[1]):
            found.append(f"{where}[1]")
        for index, item in enumerate(value):
            found += credential_keys(item, f"{where}[{index}]")
    elif isinstance(value, str) and len(value) > 2:
        text = value.strip()
        if _bearer(text):
            found.append(where)
        if text[:1] in '[{"':
            with contextlib.suppress(ValueError):
                found += credential_keys(json.loads(text), f"{where}<json>")
        if text.startswith(('{\\"', '[\\"')):
            with contextlib.suppress(ValueError):
                found += credential_keys(json.loads(f'"{text}"'), f"{where}<json>")
        if "=" in text:
            pairs = urllib.parse.parse_qsl(text.lstrip("?"), keep_blank_values=False)
            found += [f"{where}<query>.{k}" for k, v in pairs if is_credential_key(k) and v]
    return found


class Recorder:
    """An httpx transport that vets, forwards, filters and records one app's exchanges."""

    def __init__(
        self,
        app: str,
        inner: httpx.BaseTransport,
        allowed: AllowedSet,
        profiles: Sequence[RouteProfile],
        app_version: str = "unknown",
    ) -> None:
        self.app = app
        self.inner = inner
        self.allowed = allowed
        self.profiles = list(profiles)
        self.app_version = app_version
        self.records: list[dict[str, Any]] = []

    def profile_for(self, path: str) -> RouteProfile:
        for profile in self.profiles:
            if profile.path_params(path) is not None:
                return profile
        raise FixtureRefused("path", path)

    def vet(self, request: httpx.Request) -> tuple[RouteProfile, dict[str, Any]]:
        """The request-time check: refuse before anything is sent."""
        body = json.loads(request.content) if request.content else None
        shape = {"path": request.url.path, "query": dict(request.url.params), "body": body}
        profile = self.profile_for(request.url.path)
        self.allowed.check_request(profile, shape)
        return profile, shape

    def handle(self, request: httpx.Request) -> httpx.Response:
        profile, shape = self.vet(request)
        response = self.inner.handle_request(request)
        response.read()
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if profile.creates:
            self.allowed.grow(answer)
        self.records.append(
            {
                "seq": len(self.records),
                "app": self.app,
                "app_version": self.app_version,
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "request": {
                    "method": request.method,
                    "path": shape["path"],
                    "route": profile.template,
                    "query": shape["query"],
                    "headers": strip_request_headers(self.app, dict(request.headers)),
                    "body": shape["body"],
                },
                "answer": {
                    "status": response.status_code,
                    "headers": strip_answer_headers(dict(response.headers)),
                    "body": filter_list(answer, self.allowed),
                },
            }
        )
        return httpx.Response(response.status_code, json=answer, headers=response.headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def cassette(self, name: str) -> dict[str, Any]:
        return {"format": FORMAT, "name": name, "source": "recorded", "records": self.records}


def write(
    cassette: Mapping[str, Any], relative: str, allowed: AllowedSet, root: CassetteRoot
) -> Path:
    """Validate, re-scan and secret-scan ``cassette``, then write it under the private root."""
    target = root.target(relative)
    Cassette.model_validate(cassette)
    findings = final_scan(cassette, allowed)
    if findings:
        raise FixtureRefused(findings[0], None)
    credentials = credential_keys(cassette)
    if credentials:
        # Paths only: the value is never printed.
        raise ValueError(
            f"secret_found: a credential-named key, or a bearer credential, holds a value at "
            f"{credentials[0]}"
        )
    text = json.dumps(cassette, indent=2, sort_keys=True) + "\n"
    if scan_text(text, str(target)):
        raise ValueError("secret_found: the cassette was not written")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", required=True, choices=sorted(CORE_READS))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixtures", default="eval/fixtures.yaml")
    args = parser.parse_args(argv)
    allowed = AllowedSet.from_fixtures(Path(args.fixtures))
    root = CassetteRoot()
    name, value = HEADERS[args.app]
    for template, query in CORE_READS[args.app]:
        recorder = Recorder(args.app, httpx.HTTPTransport(), allowed, [RouteProfile(template)])
        with httpx.Client(
            base_url=args.base_url, transport=recorder.transport(), headers={name: value}
        ) as client:
            client.get(template, params=query)
        slug = template.strip("/").replace("/", ".")
        written = write(
            recorder.cassette(f"{args.app}.{slug}"),
            f"{args.app}/{slug}.core.cassette.json",
            allowed,
            root,
        )
        print(f"wrote {written.relative_to(root.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
