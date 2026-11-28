# Origin: miForge (Onegaishimas/miForge) backend/tests/support/siblings.py @ e4251e4
# Mode: adapt (docs/REUSE.md). Kept: the variable-first rule, loud skip, fail under a switch.
# Changed: four siblings (miWorkbench, miServer, miDataworks, miForge), miAssist's switches.
"""The one place a test finds a sibling checkout (Foundation task 1.2; PADR ADR-011).

``tests/unit/test_no_inline_sibling_lookup.py`` keeps this the only implementation.

Rules:

- **Variables first, in order.** The first SET variable wins, even when its path does not exist:
  a variable is the operator saying where the sibling is, so a wrong path surfaces as "absent"
  rather than falling through to whatever happens to sit beside the checkout.
- **Then the folder beside this checkout.**
- **Absent means skip, loudly; under any require switch it means fail.**
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import pytest


@dataclass(frozen=True)
class Sibling:
    """A sibling repository: its key, display name, the variables that move it, its folders."""

    key: str
    name: str
    env: tuple[str, ...]
    folders: tuple[str, ...]


MIWORKBENCH = Sibling(
    "miworkbench",
    "miWorkbench",
    env=("MIASSIST_MIWORKBENCH_ROOT", "MIWORKBENCH_REPO"),
    folders=("miWorkbench",),
)
MISERVER = Sibling(
    "miserver", "miServer", env=("MIASSIST_MISERVER_ROOT", "MISERVER_REPO"), folders=("miServer",)
)
MIDATAWORKS = Sibling(
    "midataworks",
    "miDataworks",
    env=("MIASSIST_MIDATAWORKS_ROOT", "MIDATAWORKS_REPO"),
    folders=("miDataworks",),
)
MIFORGE = Sibling(
    "miforge", "miForge", env=("MIASSIST_MIFORGE_ROOT", "MIFORGE_REPO"), folders=("miForge",)
)
SIBLINGS = (MIWORKBENCH, MISERVER, MIDATAWORKS, MIFORGE)

#: Either set to "1" turns an absent sibling into a failure (miStudio CLAUDE.md).
REQUIRE_SWITCHES = ("MIASSIST_REQUIRE_CROSS_REPO_CHECKS", "MISTUDIO_REQUIRE_CROSS_REPO_CHECKS")

#: miAssist's repository root (this file is tests/support/siblings.py).
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Located:
    """Where a sibling was looked for: the path, the spelling that chose it, every one tried."""

    path: Path
    spelling: str
    tried: tuple[str, ...]


def locate(sibling: Sibling, *, base: Path | None = None) -> Located:
    """Find ``sibling``: the first set variable, else the first existing folder beside
    ``base`` (default: the directory holding this checkout), else the first folder name."""
    parent = REPO_ROOT.parent if base is None else base
    tried = (*sibling.env, *(f"../{folder}" for folder in sibling.folders))
    for name in sibling.env:
        value = os.environ.get(name)
        if value:
            return Located(Path(value).expanduser(), name, tried)
    for folder in sibling.folders:
        candidate = parent / folder
        if candidate.is_dir():
            return Located(candidate, f"../{folder}", tried)
    first = sibling.folders[0]
    return Located(parent / first, f"../{first}", tried)


def required() -> bool:
    """True when any require switch is "1"."""
    return any(os.environ.get(name) == "1" for name in REQUIRE_SWITCHES)


def absent(message: str) -> NoReturn:
    """Skip loudly; fail instead when cross-repo checks are required."""
    if required():
        pytest.fail(
            f"{message} - and cross-repo checks are required ({' / '.join(REQUIRE_SWITCHES)})"
        )
    pytest.skip(message)


def not_checked_out(sibling: Sibling, located: Located, consequence: str) -> str:
    """The message for an absent sibling: every spelling tried, then what goes unchecked."""
    return (
        f"{sibling.name} is not checked out at {located.path} "
        f"(tried {', '.join(located.tried)}); {consequence}"
    )


def require_root(sibling: Sibling, consequence: str) -> Path:
    """The sibling's root, or a loud skip (a failure under a switch) naming where it looked."""
    located = locate(sibling)
    if not located.path.is_dir():
        absent(not_checked_out(sibling, located, consequence))
    return located.path
