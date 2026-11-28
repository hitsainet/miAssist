"""The real entry point serves without an access log (R1M-19; Foundation task 4.2).

uvicorn's default access log prints request paths, and ``/p/<key>/mcp`` carries the per-person key.
This starts ``python -m miassist`` in a subprocess, requests paths carrying a sample key, and finds
the key in neither stdout nor stderr. *Control:* ``access_log=True`` in ``__main__`` → red.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.support.entrypoint import running_server

SAMPLE_KEY = "abcdefghijklmnopqrstuvwxyz"[:26]


def test_key_not_in_process_output() -> None:
    with running_server() as (base, proc):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        headers = {"accept": "application/json, text/event-stream"}
        answer = httpx.post(base + f"/p/{SAMPLE_KEY}/mcp", json=body, headers=headers, timeout=5)
        assert answer.status_code == 200, answer.text
        for path in (f"/p/{SAMPLE_KEY}", "/health"):
            httpx.get(base + path, timeout=5)
        proc.terminate()
        out, err = proc.communicate(timeout=10)
    output = out.decode() + err.decode()
    assert SAMPLE_KEY not in output, f"the key reached the process output:\n{output[-2000:]}"
    assert "/p/" not in output


def test_uvicorn_runs_without_access_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``uvicorn.run`` call itself passes ``access_log=False`` (one call, exact kwargs)."""
    import uvicorn

    from miassist import __main__ as entry

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.delenv("MIASSIST_MIGRATE", raising=False)
    assert entry.main() == 0
    assert len(calls) == 1
    assert calls[0]["access_log"] is False
    assert calls[0]["log_config"] is None


def test_configure_disables_the_access_logger() -> None:
    """Defence in depth: even if an access log were turned on, its logger is disabled."""
    import logging

    from miassist import logging as ma_logging

    ma_logging.configure()
    try:
        assert logging.getLogger("uvicorn.access").disabled is True
        assert logging.getLogger("mcp").level == logging.WARNING
    finally:
        logging.getLogger("uvicorn.access").disabled = False
