"""The honest end (001 FR-28, AC-28.1, AC-28.2; A25, R1M-10; FTID §3.13).

The ONE sanctioned way to say this installation cannot do something: ``honest_end(app_ids,
installed)`` renders ``guidance/honest_end.yaml``'s one-app or any-of form with ``apps.yaml``'s
display names. It refuses an app that IS installed (the form is for absent apps only). FR-5's
absent answer and every playbook end that needs an absent app (003-005) carry its output in
``data.honest_end``; FR-22's absence scan removes exactly this rendering and nothing else.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from functools import cache

from miassist.adapters.base import ProgrammingError
from miassist.guidance.loader import Guidance

APP_ORDER = ("miworkbench", "miserver", "midataworks", "miforge")


@cache
def _default() -> Guidance:
    return Guidance()


def honest_end(
    app_ids: Sequence[str], installed: Collection[str], guidance: Guidance | None = None
) -> str:
    """``needs <App>, which isn't part of this installation`` (or the any-of form)."""
    words = guidance or _default()
    wanted = [a for a in APP_ORDER if a in set(app_ids)]
    if not wanted or len(wanted) != len(app_ids):
        raise ProgrammingError(f"honest_end needs known absent app ids, got {list(app_ids)!r}")
    present = [a for a in wanted if a in installed]
    if present:
        raise ProgrammingError(f"honest_end is for absent apps only; {present} are installed")
    names = [words.app_name(a) for a in wanted]
    form = words.honest_end
    if len(names) == 1:
        return words.render(form.one, {"app": names[0]}).text
    joined = ", ".join(names[:-1]) + form.joiner + names[-1]
    return words.render(form.any_of, {"apps": joined}).text
