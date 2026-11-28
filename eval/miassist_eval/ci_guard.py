"""The CI credential guard (FR-002.16a; FTID §7.4; M13; R1M-18): no paid model run and no model
credential in any workflow, read from the PARSED workflow files."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

ALLOWED_CI_SECRETS: dict[str, str] = {
    "GITHUB_TOKEN": "GitHub's own job token",
    "HITSAINET_SYNC": "mirror sync (sync-to-clean.yml)",
    "DOCKERHUB_USERNAME": "image build login",
    "DOCKERHUB_TOKEN": "image build login",
}
MODEL_WORDS = re.compile(r"(?i)(anthropic|openai|claude|model|llm)")
CREDENTIAL_NAME = re.compile(r"(?i)(token|key|secret|auth)")
SECRET_REF = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)")
ONE_SECRET = re.compile(r"^\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
#: ``${{ github.token }}`` is GitHub's own job token, the same value as ``secrets.GITHUB_TOKEN``.
JOB_TOKEN = re.compile(r"^\$\{\{\s*github\.token\s*\}\}$")
PAID_INVOCATION = re.compile(
    r"(--tier[ =]+1b|--tier[ =]+2\b|(^|[\s;&|(])claude(\s|$)|drivers\.open_webui|open[-_]webui|"
    r"@anthropic-ai/claude-code)",
    re.IGNORECASE | re.MULTILINE,
)


def load_workflows(directory: Path) -> dict[str, Any]:
    return {
        str(p): yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.y*ml"))
    }


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any, Any]]:
    """``(path, key, value)`` for every mapping entry; strings in lists as ``(path, None, s)``."""
    if isinstance(node, Mapping):
        for k, v in node.items():
            here = f"{path}.{k}"
            yield here, k, v
            yield from _walk(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                yield f"{path}[{i}]", None, v
            yield from _walk(v, f"{path}[{i}]")


def findings(workflows: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for name, doc in workflows.items():
        for path, key, value in _walk(doc):
            where = f"{name}{path}"
            if isinstance(value, str):
                for secret in SECRET_REF.findall(value):
                    if secret not in ALLOWED_CI_SECRETS:
                        out.append(f"{where}: secrets.{secret} is not an allowed CI secret")
                if "toJSON(secrets)" in value.replace(" ", "") or "secrets[" in value:
                    out.append(f"{where}: reads the whole secrets context")
                if key == "run" and PAID_INVOCATION.search(value):
                    out.append(f"{where}: invokes a paid client or tier (M13)")
            if key == "secrets" and value == "inherit":
                out.append(f"{where}: secrets: inherit")
            parent = path.rsplit(".", 2)[-2] if path.count(".") >= 2 else ""
            if (
                isinstance(key, str)
                and parent in ("env", "with", "secrets")
                and CREDENTIAL_NAME.search(key)
            ):
                text = str(value).strip() if isinstance(value, str) else ""
                if JOB_TOKEN.match(text):
                    continue
                m = ONE_SECRET.match(text)
                if not m or m.group(1) not in ALLOWED_CI_SECRETS:
                    out.append(f"{where}: credential-like {key} not fed from one allowed secret")
    return out


def self_check(workflows: Mapping[str, Any]) -> None:
    """The walker must see something: a workflow, a run: step and a secrets. reference."""
    assert workflows, "no workflow parsed"
    runs = [v for d in workflows.values() for _, k, v in _walk(d) if k == "run"]
    refs = [
        v
        for d in workflows.values()
        for _, _, v in _walk(d)
        if isinstance(v, str) and SECRET_REF.search(v)
    ]
    assert runs, "no run: step found"
    assert refs, "no secrets. reference found"
