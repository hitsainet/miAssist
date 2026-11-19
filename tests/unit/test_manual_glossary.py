"""The manual's Glossary page is generated from the guidance glossary (001 FTASKS 13.2)."""

from __future__ import annotations

from scripts.write_manual_glossary import TARGET, render

from miassist.guidance.loader import Guidance


def test_page_is_generated() -> None:
    assert (
        TARGET.read_text(encoding="utf-8") == render()
    ), "run python -m scripts.write_manual_glossary"


def test_every_entry_is_on_the_page() -> None:
    page = TARGET.read_text(encoding="utf-8")
    for entry in Guidance().glossary.values():
        assert f"\n## {entry.term}\n" in page, entry.term
        assert entry.plain in page, entry.term
