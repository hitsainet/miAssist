"""The request-body cap (A24; 001 FTASKS 4.12; NC-A24-4)."""

from __future__ import annotations

import pytest

from tests.support.app_factory import client

BIG = b"x" * 2048


@pytest.mark.parametrize("with_length", [True, False], ids=["with-length", "no-length"])
def test_413(with_length: bool) -> None:
    with client(max_request_body_bytes=1024) as test_client:
        if with_length:
            response = test_client.post(
                "/mcp", content=BIG, headers={"content-type": "application/json"}
            )
        else:
            response = test_client.post(
                "/mcp",
                content=iter([BIG[:600], BIG[600:]]),
                headers={"content-type": "application/json"},
            )
    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_small_request_served() -> None:
    with client(max_request_body_bytes=1024) as test_client:
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
