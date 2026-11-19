"""Write the manual's Glossary page from ``src/miassist/guidance/glossary.yaml`` (001 FTASKS 13.2).

    python -m scripts.write_manual_glossary

The page is generated, never edited by hand: ``tests/unit/test_manual_glossary.py`` regenerates it
and fails when the committed ``manual/docs/glossary.md`` differs, so the manual and the
``miassist_glossary`` tool cannot drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

from miassist.guidance.loader import Guidance

TARGET = Path(__file__).resolve().parents[1] / "manual" / "docs" / "glossary.md"
HEADER = """---
title: Glossary
---

# Glossary

The words miAssist explains. Your assistant shows the same entries with `miassist_glossary`, and
every result links the words it uses.
"""


def render(words: Guidance | None = None) -> str:
    glossary = (words or Guidance()).glossary
    parts = [HEADER]
    for key in sorted(glossary, key=lambda k: glossary[k].term.lower()):
        entry = glossary[key]
        parts.append(f"\n## {entry.term}\n\n{entry.plain}\n")
        if entry.good:
            parts.append(f"\nWhat good looks like: {entry.good}\n")
        if entry.aliases:
            parts.append(f"\nAlso called: {', '.join(entry.aliases)}.\n")
        if entry.see_also:
            names = ", ".join(glossary[k].term for k in entry.see_also)
            parts.append(f"\nSee also: {names}.\n")
    return "".join(parts)


def main() -> int:
    TARGET.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
