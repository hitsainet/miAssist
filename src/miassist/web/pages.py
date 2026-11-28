"""The per-person pages (001 FR-6, FR-7, FR-20; FTDD §5.1): ``/p/new``, ``/p/{key}`` and its two
POSTs. Server-rendered with Jinja2 autoescape, no JavaScript, no CORS headers. A malformed key is a
404. Forget is two steps (confirm). Nothing is stored until a setting is saved.
"""

from __future__ import annotations

import base64
import secrets
from importlib import resources
from typing import Any
from urllib.parse import parse_qs

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, PackageLoader, select_autoescape

from miassist.server.keyshim import KEY_PATTERN
from miassist.store.degrading import StoreUnavailable
from miassist.store.repository import hash_key

LEVELS = ("beginner", "expert")


def new_key() -> str:
    """128 bits from ``secrets.token_bytes(16)``, 26 lower-case base32 characters, no padding."""
    return base64.b32encode(secrets.token_bytes(16)).decode().rstrip("=").lower()


def _text() -> dict[str, Any]:
    raw = resources.files("miassist.guidance").joinpath("pages.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(raw)
    return data


def environment() -> Environment:
    """The pages' one template environment (autoescape on, A8/T-5)."""
    return Environment(
        loader=PackageLoader("miassist.web", "templates"), autoescape=select_autoescape(["html"])
    )


def make_router(get_runtime: Any) -> APIRouter:
    env = environment()
    text = _text()
    router = APIRouter()

    def not_found() -> Response:
        return JSONResponse(
            {"error": "not_found", "detail": "open /p/new for a personal link"}, 404
        )

    def base_url(request: Request) -> str:
        configured = get_runtime().settings.public_base_url
        return (configured or str(request.base_url)).rstrip("/")

    @router.get("/p/new", response_class=HTMLResponse)
    async def new_page(request: Request) -> Response:
        key = new_key()
        html = env.get_template("new.html").render(
            title=text["new_title"],
            text=text,
            url=f"{base_url(request)}/p/{key}/mcp",
            page=f"/p/{key}",
        )
        return HTMLResponse(html, headers={"cache-control": "no-store"})

    async def render_key(key: str, notice: str | None = None, confirm: bool = False) -> Response:
        level = await get_runtime().store.level(hash_key(key)) or "beginner"
        html = env.get_template("key.html").render(
            title=text["key_title"],
            text=text,
            page=f"/p/{key}",
            level=level,
            levels=LEVELS,
            notice=notice,
            confirm=confirm,
        )
        return HTMLResponse(html, headers={"cache-control": "no-store"})

    @router.get("/p/{key}", response_class=HTMLResponse)
    async def key_page(key: str, saved: str | None = None) -> Response:
        if not KEY_PATTERN.fullmatch(key):
            return not_found()
        notices = {
            "1": text["key_saved"],
            "0": text["key_not_saved"],
            "forgotten": text["key_forgotten"],
        }
        return await render_key(key, notices.get(saved or ""))

    async def form(request: Request) -> dict[str, str]:
        """An urlencoded form (no multipart, so no extra dependency; A14: no uploads)."""
        body = (await request.body()).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(body, max_num_fields=4).items()}

    @router.post("/p/{key}/guidance")
    async def save_level(key: str, request: Request) -> Response:
        level = (await form(request)).get("level", "")
        if not KEY_PATTERN.fullmatch(key) or level not in LEVELS:
            return not_found()
        try:
            await get_runtime().store.set_level(hash_key(key), level)
            outcome = "1"
        except StoreUnavailable:
            outcome = "0"
        return RedirectResponse(f"/p/{key}?saved={outcome}", status_code=303)

    @router.post("/p/{key}/forget")
    async def forget(key: str, request: Request) -> Response:
        confirm = (await form(request)).get("confirm")
        if not KEY_PATTERN.fullmatch(key):
            return not_found()
        if confirm != "yes":
            return await render_key(key, confirm=True)
        try:
            await get_runtime().store.forget(hash_key(key))
            outcome = "forgotten"
        except StoreUnavailable:
            outcome = "0"
        return RedirectResponse(f"/p/{key}?saved={outcome}", status_code=303)

    return router
