"""In-process uvicorn listeners on ephemeral 127.0.0.1 ports, one asyncio loop (TD-1, TD-2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import uvicorn


@dataclass
class Listener:
    url: str
    server: uvicorn.Server
    task: asyncio.Task[Any]

    async def stop(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.task, timeout=10)


async def serve(app: Any, host: str = "127.0.0.1") -> Listener:
    config = uvicorn.Config(
        app, host=host, port=0, log_level="warning", access_log=False, lifespan="auto"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    sock = server.servers[0].sockets[0]
    port = sock.getsockname()[1]
    return Listener(url=f"http://{host}:{port}", server=server, task=task)
