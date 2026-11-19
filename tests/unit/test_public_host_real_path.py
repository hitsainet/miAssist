"""The public request as it really arrives (001 FTASKS 14.5, push 001-P; A21, R2M-13).

The public path is Cloudflare -> the cloudflared tunnel -> ingress-nginx -> the pod. The tunnel
rule for ``mcp-assist.hitsai.net`` REWRITES Host to ``mcp-assist.hitsai.local`` (``httpHostHeader``;
suite memory ``public-proxy-rewrites-host-header``), so the pod sees that Host plus Cloudflare's
``cf-ray`` / ``cf-connecting-ip`` and the proxies' forwarding headers. Observed before the flip
(2026-11-17): ``/health`` and ``/mcp`` answered the guard's own 404 through Cloudflare.

These tests send that request in process, with the settings built from the COMMITTED ConfigMap
(``gitops/pilot/config.yaml``), not from a test list, so dropping the arriving host from
``MIASSIST_ALLOWED_HOSTS`` or from the Ingress turns them red. Both branches run every time (V-3):
the guard's 404 with the constant ``False``, admitted with it ``True``; one test also runs at the
committed value.
"""

from __future__ import annotations

from typing import Any

import pytest

from miassist.web import exposure
from tests.support.app_factory import MCP_HEADERS, client
from tests.unit.test_manifests import config_data, of_kind

PUBLIC = "mcp-assist.hitsai.net"
#: The Host the tunnel rule sends (its ``httpHostHeader``), read from the rule on 2026-11-17.
TUNNEL_HOST = "mcp-assist.hitsai.local"
GUARD_BODY = {"error": "not_found"}
KEY = "abcdefghijklmnopqrstuvwxyz"
PATHS = ["/health", "/mcp", f"/p/{KEY}/mcp", "/p/new"]

#: What cloudflared and ingress-nginx add (ingress-nginx sets X-Forwarded-Host to the Host it got).
REAL_PATH_HEADERS = {
    "host": TUNNEL_HOST,
    "cf-ray": "8f00000000000000-EWR",
    "cf-connecting-ip": "203.0.113.9",
    "cf-ipcountry": "US",
    "cf-visitor": '{"scheme":"https"}',
    "cdn-loop": "cloudflare",
    "x-forwarded-for": "203.0.113.9, 192.0.2.10",
    "x-forwarded-proto": "https",
    "x-forwarded-port": "80",
    "x-real-ip": "203.0.113.9",
    "x-scheme": "http",
}
#: The forwarded host as ingress-nginx sets it, and the original name in case a proxy keeps it.
FORWARDED = {
    "none": {},
    "rewritten": {"x-forwarded-host": TUNNEL_HOST},
    "original": {"x-forwarded-host": PUBLIC},
}


def committed_settings() -> dict[str, Any]:
    data = config_data()
    return {
        "allowed_hosts": data["MIASSIST_ALLOWED_HOSTS"],
        "public_base_url": data["MIASSIST_PUBLIC_BASE_URL"],
    }


def is_guard(response: Any) -> bool:
    if response.status_code != 404:
        return False
    try:
        return bool(response.json() == GUARD_BODY)
    except ValueError:
        return False


def _request(test_client: Any, path: str, headers: dict[str, str]) -> Any:
    if path.endswith("/mcp"):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        return test_client.post(path, json=body, headers={**MCP_HEADERS, **headers})
    return test_client.get(path, headers=headers)


def _tool_names(response: Any) -> list[str]:
    return [tool["name"] for tool in response.json()["result"]["tools"]]


def test_the_arriving_host_is_routed_and_allowed() -> None:
    """The rewritten Host is on the Ingress (or ingress-nginx 404s it) and in the Host check."""
    ingress = [r["host"] for ing in of_kind("Ingress") for r in ing["spec"]["rules"]]
    allowed = [h.strip() for h in config_data()["MIASSIST_ALLOWED_HOSTS"].split(",")]
    assert TUNNEL_HOST in ingress, "the tunnel's rewritten Host is not on the Ingress"
    assert TUNNEL_HOST in allowed, "the tunnel's rewritten Host is not in MIASSIST_ALLOWED_HOSTS"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("forwarded", sorted(FORWARDED))
@pytest.mark.parametrize("approved", [False, True])
def test_real_path(
    monkeypatch: pytest.MonkeyPatch, approved: bool, forwarded: str, path: str
) -> None:
    monkeypatch.setattr(exposure, "PUBLIC_HOST_APPROVED", approved)
    headers = {**REAL_PATH_HEADERS, **FORWARDED[forwarded]}
    with client(**committed_settings()) as test_client:
        response = _request(test_client, path, headers)
    if not approved:
        assert is_guard(response), (response.status_code, response.text)
        return
    assert response.status_code == 200, (response.status_code, response.text)
    if path.endswith("/mcp"):
        assert _tool_names(response), "admitted but no tools listed"
    if path == "/p/new":
        assert f"https://{PUBLIC}/p/" in response.text, "the personal link is not the public host"


def test_real_path_at_the_committed_value_lists_the_lans_tools() -> None:
    """No monkeypatch: at the committed constant the real-path request is admitted, and its
    ``tools/list`` equals a LAN request's (14.5's off-LAN check, in process)."""
    with client(**committed_settings()) as test_client:
        public = _request(test_client, "/mcp", REAL_PATH_HEADERS)
        lan = _request(test_client, "/mcp", {"host": "k8s-miassist.hitsai.local"})
    assert lan.status_code == 200, lan.text
    assert public.status_code == 200, (public.status_code, public.text)
    assert public.json()["result"] == lan.json()["result"]
