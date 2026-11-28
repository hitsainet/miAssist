"""Every file carrying an origin header has a row in ``docs/REUSE.md`` (PADR ADR-001; 001 FTASKS
13.3): a copy without a recorded origin is a fork nobody knows they maintain."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("src", "tests", "scripts", ".github", "gitops", "manual/scripts", "miassist_fixtures")


def headed(root: Path) -> list[str]:
    out = []
    for folder in SCANNED:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".yml", ".yaml", ".mjs"):
                continue
            head = path.read_text(encoding="utf-8", errors="replace")[:400]
            if "# Origin:" in head or "// Origin:" in head:
                out.append(str(path.relative_to(root)))
    return out


def test_every_origin_header_has_a_row() -> None:
    index = (ROOT / "docs/REUSE.md").read_text(encoding="utf-8")
    missing = [p for p in headed(ROOT) if f"`{p}`" not in index]
    assert missing == [], f"add a docs/REUSE.md row for: {missing}"


def test_self_test(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/copied.py").write_text("# Origin: elsewhere @ abc\n")
    (tmp_path / "src/own.py").write_text("x = 1\n")
    assert headed(tmp_path) == ["src/copied.py"]
