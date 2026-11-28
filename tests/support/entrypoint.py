"""Run the real entry point, ``python -m miassist``, in a subprocess on a free port."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_server(
    extra_env: dict[str, str] | None = None,
) -> Iterator[tuple[str, subprocess.Popen[bytes]]]:
    """Yield ``(base_url, process)``; the process is stopped and its output collected after."""
    port = free_port()
    env = {
        **os.environ,
        "MIASSIST_HOST": "127.0.0.1",
        "MIASSIST_PORT": str(port),
        "MIASSIST_ALLOWED_HOSTS": "127.0.0.1",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "1",
        "PYTHONUNBUFFERED": "1",
        # Run THIS checkout's code: an editable install elsewhere must not win (a head-suite run in
        # a second checkout found the subprocess importing the other tree's package).
        "PYTHONPATH": str(REPO_ROOT / "src"),
        **(extra_env or {}),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "miassist"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"the server exited: {proc.communicate()[1].decode()[-2000:]}")
            try:
                httpx.get(base + "/health", timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("the server did not start within 20 s")
        yield base, proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
