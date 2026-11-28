"""The /p/ pages and the key's format (001 FR-6, FR-7, FR-20; FTASKS 7.3, 7.4)."""

from __future__ import annotations

import re

from miassist.store.repository import hash_key
from miassist.web.pages import new_key
from tests.support.app_factory import client
from tests.support.memory_store import MemoryStore

KEY = "abcdefghijklmnopqrstuvwxyz"


def test_format_and_uniqueness() -> None:
    keys = {new_key() for _ in range(10_000)}
    assert len(keys) == 10_000
    assert all(re.fullmatch(r"^[a-z2-7]{26}$", k) for k in keys)


def test_new_page_shows_a_fresh_key_and_stores_nothing() -> None:
    store = MemoryStore()
    with client(store=store) as test_client:
        first = test_client.get("/p/new").text
        second = test_client.get("/p/new").text
    keys = [re.search(r"/p/([a-z2-7]{26})/mcp", page).group(1) for page in (first, second)]  # type: ignore[union-attr]
    assert keys[0] != keys[1]
    assert store.write_calls == 0 and store.levels == {}


def test_save_and_forget_two_steps() -> None:
    store = MemoryStore()
    with client(store=store) as test_client:
        saved = test_client.post(
            f"/p/{KEY}/guidance", data={"level": "expert"}, follow_redirects=False
        )
        assert saved.status_code == 303
        assert store.levels == {hash_key(KEY): "expert"}
        assert "selected>expert" in test_client.get(f"/p/{KEY}").text.replace(
            '"expert" selected', "selected>expert"
        )
        ask = test_client.post(f"/p/{KEY}/forget", follow_redirects=False)
        assert ask.status_code == 200 and store.levels, "forget is two steps"
        done = test_client.post(f"/p/{KEY}/forget", data={"confirm": "yes"}, follow_redirects=False)
        assert done.status_code == 303 and store.levels == {}


def test_malformed_key_pages_404() -> None:
    with client() as test_client:
        assert test_client.get("/p/NOTAKEY").status_code == 404
        assert test_client.post("/p/NOTAKEY/guidance", data={"level": "expert"}).status_code == 404


def test_store_down_page_says_not_saved() -> None:
    with client(store=MemoryStore(down=True)) as test_client:
        page = test_client.post(f"/p/{KEY}/guidance", data={"level": "expert"})
    assert "Not saved right now" in page.text


def test_autoescape() -> None:
    """The environment the pages use escapes markup in every value it renders."""
    from miassist.web.pages import environment

    html = (
        environment()
        .get_template("key.html")
        .render(
            title="<i>t</i>",
            text={},
            page="/p/x",
            level="beginner",
            levels=["<script>x</script>"],
            notice="<script>alert(1)</script>",
            confirm=False,
        )
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
