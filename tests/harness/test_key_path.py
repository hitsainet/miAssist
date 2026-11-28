"""The key in the URL path reaches a tool, and changes nothing else (001 FR-6, FR-7, FR-21;
FTASKS 7.2, 7.5, 10.5, 12.2's auth half)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from tests.support.app_factory import client
from tests.support.fake_apps import all_fakes
from tests.support.http_mcp import call_tool, rpc
from tests.support.memory_store import MemoryStore

K1 = "abcdefghijklmnopqrstuvwxyz"
K2 = "zyxwvutsrqponmlkjihgfedcba"
URLS = {
    f"{a}_url": f"http://{a}.test" for a in ("miworkbench", "miserver", "midataworks", "miforge")
}


def keyed(key: str | None) -> str:
    return f"/p/{key}/mcp" if key else "/mcp"


def test_tool_sees_key() -> None:
    with client() as test_client:
        data = call_tool(test_client, keyed(K1), "miassist_status")["structuredContent"]["data"]
        assert data["remembered"] is True
        assert data["key_fp"] == hashlib.sha256(K1.encode()).hexdigest()[:8]
        bare = call_tool(test_client, "/mcp", "miassist_status")["structuredContent"]["data"]
        assert bare["remembered"] is False and bare["key_fp"] is None


def requests_seen(
    path: str, headers: dict[str, str] | None = None
) -> tuple[list[Any], dict[str, Any], list[str]]:
    fakes = all_fakes()
    fakes["miforge"].on("GET", "/api/v1/runs", {"runs": [{"name": "r1"}], "total": 1})
    fakes["miforge"].on("GET", "/api/v1/packs", [])
    fakes["miforge"].on("GET", "/api/v1/checkpoints", {"items": []})
    transports = {a: f.transport() for a, f in fakes.items()}
    with client(transports=transports, apps="miforge", **URLS) as test_client:
        tools = [t["name"] for t in rpc(test_client, path, "tools/list", headers=headers)["tools"]]
        fakes["miforge"].requests.clear()
        result = call_tool(test_client, path, "miassist_overview", {"app": "miforge"}, headers)
    seen = [
        (
            r.method,
            r.path,
            sorted(r.params.items()),
            r.body,
            sorted(k for k in r.headers if k.startswith("x-")),
        )
        for r in fakes["miforge"].requests
        if r.path != "/api/health"
    ]
    return seen, result["structuredContent"]["data"], tools


@pytest.mark.parametrize(
    "variant",
    [
        ("/p/" + K1 + "/mcp", None),
        ("/p/" + K2 + "/mcp", None),
        ("/mcp", {"authorization": "Bearer garbage-test-only"}),
        ("/p/" + K1 + "/mcp", {"authorization": "Bearer other-test-only"}),
    ],
    ids=["key1", "key2", "bare-with-bearer", "key-with-bearer"],
)
def test_same_calls_any_key(variant: tuple[str, dict[str, str] | None]) -> None:
    baseline = requests_seen("/mcp")
    assert baseline[0], "the overview made no request: the comparison would be vacuous"
    assert requests_seen(*variant) == baseline


@pytest.mark.parametrize(
    "path", ["/p/ABC/mcp", "/p/abc/mcp", "/p/" + "A" * 26 + "/mcp", "/p/" + K1 + "1/mcp"]
)
def test_malformed_key_404(path: str) -> None:
    with client() as test_client:
        response = test_client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 404
    assert "/p/new" in response.json()["detail"]


def test_level_persists_and_changes_only_explain() -> None:
    store = MemoryStore()
    with client(store=store) as test_client:
        first = call_tool(test_client, keyed(K1), "miassist_glossary", {"term": "probe"})[
            "structuredContent"
        ]
        assert first["guidance"] == "beginner" and "explain" in first
        saved = call_tool(test_client, keyed(K1), "miassist_set_guidance", {"level": "expert"})
        assert saved["structuredContent"]["data"] == {"remembered": True, "level": "expert"}
        second = call_tool(test_client, keyed(K1), "miassist_glossary", {"term": "probe"})[
            "structuredContent"
        ]
        assert second["guidance"] == "expert" and "explain" not in second
        assert first["data"] == second["data"] and first["next_steps"] == second["next_steps"]
        other = call_tool(test_client, keyed(K2), "miassist_glossary", {"term": "probe"})[
            "structuredContent"
        ]
        assert other["guidance"] == "beginner"


def test_set_guidance_without_key_is_not_an_error() -> None:
    with client() as test_client:
        result = call_tool(test_client, "/mcp", "miassist_set_guidance", {"level": "expert"})
    assert result["isError"] is False
    assert result["structuredContent"]["data"]["remembered"] is False


def test_store_down() -> None:
    with client(store=MemoryStore(down=True)) as test_client:
        saved = call_tool(test_client, keyed(K1), "miassist_set_guidance", {"level": "expert"})
        assert saved["structuredContent"]["unavailable"] == "settings_store"
        assert saved["isError"] is False
        status = call_tool(test_client, keyed(K1), "miassist_status")
        assert status["isError"] is False and status["structuredContent"]["guidance"] == "beginner"


def test_reads_write_nothing() -> None:
    store = MemoryStore()
    with client(store=store) as test_client:
        for name, args in [
            ("miassist_guide", {}),
            ("miassist_glossary", {}),
            ("miassist_glossary", {"term": "auroc"}),
            ("miassist_status", {}),
        ]:
            call_tool(test_client, keyed(K1), name, args)
    assert store.write_calls == 0


# -- R1 review fix (OR1-001-4), 2026-11-16: DNS-rebinding protection is on ---------------------

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.mark.parametrize(
    "headers",
    [{"host": "attacker.example"}, {"origin": "http://attacker.example"}],
    ids=["foreign-host", "foreign-origin"],
)
def test_dns_rebinding_refused(headers: dict[str, str]) -> None:
    """A page on another site, resolved to this host, cannot drive the open endpoint through a
    LAN browser: a foreign Host or Origin is refused before any tool runs."""
    with client() as test_client:
        ok = test_client.post("/mcp", json=LIST, headers=MCP_HEADERS)
        assert ok.status_code == 200
        refused = test_client.post("/mcp", json=LIST, headers={**MCP_HEADERS, **headers})
        keyed = test_client.post(f"/p/{K1}/mcp", json=LIST, headers={**MCP_HEADERS, **headers})
    assert refused.status_code in (400, 403, 421), refused.status_code
    assert keyed.status_code in (400, 403, 421), keyed.status_code
