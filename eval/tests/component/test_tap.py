"""FR-002.17: byte identity through the tap; JSON and event-stream answers; N calls give N lines."""

from __future__ import annotations

import json

import httpx
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from miassist_eval.servers import serve
from miassist_eval.tap import Tap, answers
from tests.support import stub_mcp


async def test_bytes_through_the_tap_equal_bytes_direct() -> None:
    payload = b'{"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"\\u00e9 x"}]}}'

    async def upstream(request):
        return Response(payload, media_type="application/json", headers={"X-Odd": "1"})

    up = await serve(Starlette(routes=[Route("/mcp", upstream, methods=["POST"])]))
    tap = Tap(upstream=up.url)
    tl = await serve(tap.app())
    try:
        body = (
            b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"x","arguments":{}}}'
        )
        async with httpx.AsyncClient() as c:
            direct = await c.post(f"{up.url}/mcp", content=body)
            tapped = await c.post(f"{tl.url}/mcp", content=body)
        assert tapped.content == direct.content == payload
        assert tapped.headers["x-odd"] == "1"
        assert tap.count() == 1 and tap.log[0]["tool"] == "x"
    finally:
        await tl.stop()
        await up.stop()


def test_event_stream_answers_are_parsed() -> None:
    body = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"isError":true}}\n\n'
    assert answers("text/event-stream", body) == [
        {"jsonrpc": "2.0", "id": 1, "result": {"isError": True}}
    ]


async def test_n_scripted_calls_give_n_lines_by_name_and_argument_hash() -> None:
    from mcp import Client

    from miassist_eval.replay import Replay
    from tests.support import harness

    rep = Replay(edge=harness.edge(), library={}, health={})
    listeners = [await serve(rep.app_for(a)) for a in harness.refs()]
    urls = dict(zip(harness.refs(), (lis.url for lis in listeners), strict=True))
    url, stop = await stub_mcp.factory()(urls)
    base = url.rsplit("/mcp", 1)[0]
    tap = Tap(upstream=base)
    tl = await serve(tap.app())
    try:
        async with Client(f"{tl.url}/mcp") as client:
            await client.list_tools()
            for i in range(3):
                await client.call_tool("read_version", {"version_id": f"evalfx-v{i}"})
        calls = [x for x in tap.log if x["method"] == "tools/call"]
        assert [c["tool"] for c in calls] == ["read_version"] * 3
        assert len({c["args_sha256"] for c in calls}) == 3
        assert tap.count("tools/list") == 1
        assert json.dumps(tap.log)  # serialisable
    finally:
        await tl.stop()
        await stop()
        for lis in listeners:
            await lis.stop()
