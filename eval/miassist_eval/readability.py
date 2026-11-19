"""Flesch–Kincaid grade (FR-002.5 rule 7; FTID §7.1).

0.39 × words/sentences + 11.8 × syllables/words − 15.59, with a vowel-group syllable count.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
_VOWELS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    w = word.lower()
    if w.endswith("'s"):
        w = w[:-2]
    count = len(_VOWELS.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(count, 1)


def fk_grade(text: str) -> float:
    words = _WORD.findall(text)
    if not words:
        return 0.0
    sentences = max(len(_SENTENCE_END.findall(text.strip())), 1)
    syl = sum(syllables(w) for w in words)
    return 0.39 * len(words) / sentences + 11.8 * syl / len(words) - 15.59
