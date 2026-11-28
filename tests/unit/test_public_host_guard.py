"""The public host stays shut in code (A21, R1M-4; Foundation task 2.7, extended by 001 FTASKS 7.6).

Both branches run on EVERY run (V-3, A43): the constant is monkeypatched to ``False`` (the guard's
404 expected) and to ``True`` (the request served), whatever the committed value. The committed
value itself is pinned by ``test_public_host_constant.py``.
"""

from __future__ import annotations

import pytest

from miassist.web import exposure
from tests.support.app_factory import MCP_HEADERS, client

GUARD_BODY = {"error": "not_found"}
PUBLIC = "mcp-assist.hitsai.net"

HEADER_CASES = {
    "cf-ray": {"cf-ray": "8f00000000000000-EWR"},
    "cf-connecting-ip": {"cf-connecting-ip": "203.0.113.9"},
    "host": {"host": PUBLIC},
    "host-upper-port": {"host": "MCP-ASSIST.HITSAI.NET:443"},
    "apex-host": {"host": "hitsai.net"},
    "x-forwarded-host": {"x-forwarded-host": PUBLIC},
    "x-original-host": {"x-original-host": PUBLIC.upper() + ":8443"},
    "forwarded": {"forwarded": f'for=203.0.113.9;proto=https;host="{PUBLIC}"'},
}
PATHS = ["/health", "/mcp", "/p/abcdefghijklmnopqrstuvwxyz/mcp", "/p/new"]


def is_guard(response) -> bool:  # type: ignore[no-untyped-def]
    """The guard's own answer: 404 with exactly ``{"error": "not_found"}``."""
    if response.status_code != 404:
        return False
    try:
        return bool(response.json() == GUARD_BODY)
    except ValueError:
        return False


def _request(test_client, path: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    if path.endswith("/mcp"):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        return test_client.post(path, json=body, headers={**MCP_HEADERS, **headers})
    return test_client.get(path, headers=headers)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("case", sorted(HEADER_CASES))
@pytest.mark.parametrize("approved", [False, True])
def test_refused(monkeypatch: pytest.MonkeyPatch, approved: bool, case: str, path: str) -> None:
    monkeypatch.setattr(exposure, "PUBLIC_HOST_APPROVED", approved)
    with client() as test_client:
        response = _request(test_client, path, HEADER_CASES[case])
    if approved:
        assert not is_guard(response), "approved but refused"
    else:
        assert is_guard(response)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize(
    "headers",
    [{}, {"host": "k8s-miassist.hitsai.local"}, {"x-forwarded-host": "mcp-assist.hitsai.local"}],
    ids=["default", "lan-host", "lan-forwarded"],
)
def test_lan_served(
    monkeypatch: pytest.MonkeyPatch, approved: bool, path: str, headers: dict[str, str]
) -> None:
    monkeypatch.setattr(exposure, "PUBLIC_HOST_APPROVED", approved)
    with client(allowed_hosts=["testserver", "k8s-miassist.hitsai.local"]) as test_client:
        response = _request(test_client, path, headers)
    assert response.status_code == 200, response.text
    assert not is_guard(response)


@pytest.mark.parametrize(
    "value",
    ["evilhitsai.net", "hitsai.network", "hitsai.local", "[::1]:8765", "notmcp-assist.hitsai.netx"],
)
def test_lookalikes_are_not_public(value: str) -> None:
    assert not exposure.is_public_request([(b"host", value.encode())])


# -- R1 review: the guard is the outermost layer and covers websockets (OR1-001-8 X-3, X-6) ----


def test_public_request_with_a_large_body_gets_the_guards_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """X-3: the guard answers before the body cap, so a public request never learns the cap."""
    monkeypatch.setattr(exposure, "PUBLIC_HOST_APPROVED", False)
    with client() as test_client:
        response = test_client.post(
            "/mcp",
            content=b"x" * 2_000_000,
            headers={**MCP_HEADERS, "cf-ray": "test-only"},
        )
    assert response.status_code == 404 and response.json() == {"error": "not_found"}


def test_public_websocket_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """X-6: a websocket through the public proxy is closed with 1008 before the app sees it."""
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(exposure, "PUBLIC_HOST_APPROVED", False)
    with (
        client() as test_client,
        pytest.raises(WebSocketDisconnect) as closed,
        test_client.websocket_connect("/mcp", headers={"cf-ray": "test-only"}) as ws,
    ):
        ws.receive_text()
    assert closed.value.code == 1008
