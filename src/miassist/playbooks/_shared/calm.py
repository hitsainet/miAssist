"""Honest ends and the absent-app word list (003 FTID §11; FPRD §5.3; A25, R1M-10).

``honest_end`` renders a playbook's "what is done" text and its step phrase from the playbook's
guidance, then appends Core's sanctioned sentence from ``results.honest_end.honest_end``; it writes
no absent-app wording of its own. ``ABSENT_APP_WORDS`` is Core's AC-5.3 list plus FR-003.5's
additions, used by 004 and 005 and by their tests.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Final

from miassist.guidance.loader import Guidance
from miassist.results.honest_end import honest_end as core_honest_end

#: Core's AC-5.3 words and FR-003.5's additions: none appears in a result BECAUSE an app is absent.
ABSENT_APP_WORDS: Final = (
    "error",
    "warning",
    "fail",
    "refus",
    "cannot",
    "unable",
    "unavailable",
    "missing",
    "not configured",
)


def words(guidance: Guidance, playbook_id: str, key: str, **slots: object) -> str:
    """One text of a playbook's words file, rendered (a missing key is a programming error)."""
    return guidance.render(guidance.playbooks[playbook_id].texts[key], dict(slots)).text


def honest_end(
    guidance: Guidance,
    playbook_id: str,
    stage: str,
    missing_apps: Sequence[str],
    installed: Collection[str],
) -> str:
    """The playbook's done text and step phrase, then Core's sanctioned sentence."""
    sentence = core_honest_end(missing_apps, installed, guidance)
    return words(
        guidance,
        playbook_id,
        "end.form",
        done=words(guidance, playbook_id, f"end.{stage}.done"),
        step=words(guidance, playbook_id, f"end.{stage}.step"),
        honest_end=sentence,
    )


def quote(app_text: object, cap: int = 200) -> str:
    """App-provided text as quoted data, capped (FTDD T4): never read as an instruction."""
    text = str(app_text).replace("`", "'")
    if len(text) > cap:
        text = text[: cap - 1] + "…"
    return f"`{text}`"


def honest_end_done(
    guidance: Guidance,
    done: str,
    missing_apps: Sequence[str] = (),
    installed: Collection[str] = (),
) -> str:
    """004/005's form (integration OVN-miassist-int-11, union of the two copies): ``done`` (the
    playbook's own sentence), then Core's sanctioned sentence for each absent app needed; with no
    absent app, ``done`` alone."""
    if not missing_apps:
        return done
    return f"{done} {core_honest_end(list(missing_apps), installed, guidance)}"
