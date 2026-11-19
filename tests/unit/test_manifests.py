"""The GitOps manifests (PADR ADR-004, ADR-005, ADR-014, ADR-017; Foundation tasks 5.6, 6.1, 6.3,
6.4, 6.7; 001 FTASKS 13.1).

Every assertion reads the PARSED manifests. The two code constants decide two rules:
``PUBLIC_HOST_APPROVED`` (no ``*.hitsai.net`` host anywhere while False, exactly the one public
host once True; A21, 14.5) and
``MIWORKBENCH_A0_LIVE`` (no ``miworkbench`` in ``MIASSIST_APPS`` while False, A12; V-11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from miassist.web import exposure

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "gitops" / "pilot"
APPLIED_BY_HAND = {"storage.yaml", "argocd/miassist-app.yaml"}
#: Written by Argo CD Image Updater (git write-back) on the gitops/pilot branch only; never on main. Argo CD reads
#: it beside the kustomization, so it is not a manifest and is never listed. Exactly this name: any other
#: unlisted file is still an error (2026-11-17: every write-back turned gitops/pilot CI red).
WRITTEN_BY_IMAGE_UPDATER = {".argocd-source-miassist.yaml"}


def docs(name: str) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all((PILOT / name).read_text()) if d]


def kustomization() -> dict[str, Any]:
    return docs("kustomization.yaml")[0]


def listed() -> list[str]:
    resources: list[str] = kustomization()["resources"]
    return resources


def all_listed_docs() -> list[dict[str, Any]]:
    return [d for name in listed() for d in docs(name)]


def of_kind(kind: str) -> list[dict[str, Any]]:
    return [d for d in all_listed_docs() if d["kind"] == kind]


def pod_specs() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for doc in all_listed_docs():
        if doc["kind"] == "Deployment":
            out.append((doc["metadata"]["name"], doc["spec"]["template"]["spec"]))
        elif doc["kind"] == "CronJob":
            out.append(
                (doc["metadata"]["name"], doc["spec"]["jobTemplate"]["spec"]["template"]["spec"])
            )
    return out


def containers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [*spec.get("initContainers", []), *spec["containers"]]


def config_data() -> dict[str, str]:
    data: dict[str, str] = docs("config.yaml")[0]["data"]
    return data


def server() -> dict[str, Any]:
    return next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "miassist")


# -- 6.7: the kustomization lists every manifest except the two applied by hand -------------


def test_every_listed_file_exists() -> None:
    assert all((PILOT / name).is_file() for name in listed())


def unlisted_files(pilot: Path, resources: list[str]) -> set[str]:
    """Manifest files under ``pilot`` that the kustomization does not list and nothing exempts."""
    files = {p.relative_to(pilot).as_posix() for p in pilot.rglob("*.yaml")}
    files -= {"kustomization.yaml"} | APPLIED_BY_HAND | WRITTEN_BY_IMAGE_UPDATER
    return files - set(resources)


def test_every_manifest_is_listed() -> None:
    assert unlisted_files(PILOT, listed()) == set()
    assert not WRITTEN_BY_IMAGE_UPDATER & set(listed())
    assert not APPLIED_BY_HAND & set(listed())
    assert set(listed()) == {
        "namespace.yaml",
        "config.yaml",
        "postgres.yaml",
        "server.yaml",
        "ingress.yaml",
        "db-backup.yaml",
    }
    assert kustomization()["images"] == [{"name": "hitsai/miassist-server", "newTag": "latest"}]


def test_one_replica() -> None:
    assert server()["spec"]["replicas"] == 1


def test_namespace_is_miassist() -> None:
    for doc in all_listed_docs():
        if doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == "miassist", doc["metadata"]["name"]


# -- 6.3: pod hardening ---------------------------------------------------------------------


@pytest.mark.parametrize("name", [n for n, _ in pod_specs()])
def test_no_gpu_for_any_container(name: str) -> None:
    spec = dict(pod_specs())[name]
    for container in containers(spec):
        env = {e["name"]: e.get("value") for e in container.get("env", [])}
        assert env.get("NVIDIA_VISIBLE_DEVICES") == "void", f"{name}/{container['name']}"
        assert "nvidia.com/gpu" not in str(container.get("resources", {}))
        assert "envFrom" not in container, f"{name}/{container['name']} uses envFrom"


def test_server_pod_hardening() -> None:
    spec = server()["spec"]["template"]["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["runAsUser"] == 10001
    assert {v["name"]: v for v in spec["volumes"]}["tmp"]["emptyDir"] is not None
    assert spec["initContainers"][0]["env"][-3:] != []
    for container in containers(spec):
        ctx = container["securityContext"]
        assert ctx["readOnlyRootFilesystem"] is True
        assert ctx["allowPrivilegeEscalation"] is False
        assert ctx["capabilities"]["drop"] == ["ALL"]
        assert ctx["runAsUser"] == 10001
        assert {m["mountPath"] for m in container["volumeMounts"]} == {"/tmp"}
        assert container["resources"]["requests"] == {"cpu": "50m", "memory": "128Mi"}
        assert container["resources"]["limits"] == {"memory": "512Mi"}
    init_env = {e["name"]: e.get("value") for e in spec["initContainers"][0]["env"]}
    assert init_env["MIASSIST_MIGRATE"] == "1"
    probe = spec["containers"][0]["readinessProbe"]["httpGet"]
    assert (probe["path"], probe["port"]) == ("/health", 8765)


def test_only_secret_is_miassist_secrets_by_key_ref() -> None:
    refs = []
    for _, spec in pod_specs():
        for container in containers(spec):
            for env in container.get("env", []):
                ref = env.get("valueFrom", {}).get("secretKeyRef")
                if ref:
                    refs.append((ref["name"], ref["key"]))
    assert refs and set(refs) == {("miassist-secrets", "POSTGRES_PASSWORD")}
    assert not of_kind("Secret"), "a Secret must never be committed; it is created in place"


# -- 6.1 and 13.1: the installed set and the hosts --------------------------------------------


def test_default_installed_set() -> None:
    """Push 001-W (14.4) added miworkbench, after 045-A0 went live (A12)."""
    assert config_data()["MIASSIST_APPS"] == "miworkbench,miserver,midataworks,miforge"


def test_no_miworkbench_before_a0() -> None:
    """The constant and the installed set move together, in one commit (A12, 14.4): no
    ``miworkbench`` while ``MIWORKBENCH_A0_LIVE`` is False, and it is listed once True."""
    apps = config_data()["MIASSIST_APPS"].split(",")
    if not exposure.MIWORKBENCH_A0_LIVE:
        assert "miworkbench" not in apps, "miWorkbench is installed only by push 001-W (A12)"
    else:
        assert "miworkbench" in apps, "MIWORKBENCH_A0_LIVE is True: push 001-W lists miworkbench"


def _hosts() -> list[str]:
    hosts = [rule["host"] for ing in of_kind("Ingress") for rule in ing["spec"]["rules"]]
    hosts += [h.strip() for h in config_data()["MIASSIST_ALLOWED_HOSTS"].split(",")]
    base = config_data().get("MIASSIST_PUBLIC_BASE_URL", "")
    if base:
        hosts.append(base)
    return hosts


PUBLIC_HOST = "mcp-assist.hitsai.net"
LAN_HOSTS = ["k8s-miassist.hitsai.local", "mcp-assist.hitsai.local"]


def check_public_hosts(approved: bool) -> None:
    """A21: no ``*.hitsai.net`` name anywhere while the constant is False; once True (push 001-P,
    14.5) exactly the one public host on the Ingress, in ``MIASSIST_ALLOWED_HOSTS`` and as
    ``MIASSIST_PUBLIC_BASE_URL``, and no other public name (no apex, no wildcard)."""
    public = [h for h in _hosts() if "hitsai.net" in h.lower()]
    if not approved:
        assert not public, f"a public host is listed before push 001-P (A21): {public}"
        return
    ingress = [r["host"] for ing in of_kind("Ingress") for r in ing["spec"]["rules"]]
    allowed = [h.strip() for h in config_data()["MIASSIST_ALLOWED_HOSTS"].split(",")]
    assert [h for h in ingress if "hitsai.net" in h.lower()] == [PUBLIC_HOST]
    assert [h for h in allowed if "hitsai.net" in h.lower()] == [PUBLIC_HOST]
    assert config_data()["MIASSIST_PUBLIC_BASE_URL"] == f"https://{PUBLIC_HOST}"
    assert sorted(public) == sorted([PUBLIC_HOST, PUBLIC_HOST, f"https://{PUBLIC_HOST}"])


def test_no_public_host_until_approved() -> None:
    check_public_hosts(exposure.PUBLIC_HOST_APPROVED)


def test_public_host_check_bites_while_unapproved() -> None:
    """V-3 (both branches every run): the committed manifests list the public host since 001-P,
    so the check under ``PUBLIC_HOST_APPROVED = False`` must refuse them: the False branch is
    exercised on every run, not only while the committed value is False."""
    with pytest.raises(AssertionError, match="before push 001-P"):
        check_public_hosts(False)


def test_lan_hosts_and_streaming() -> None:
    ingress = of_kind("Ingress")[0]
    expected = LAN_HOSTS + ([PUBLIC_HOST] if exposure.PUBLIC_HOST_APPROVED else [])
    assert [r["host"] for r in ingress["spec"]["rules"]] == expected
    notes = ingress["metadata"]["annotations"]
    assert notes["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "3600"
    assert notes["nginx.ingress.kubernetes.io/proxy-send-timeout"] == "3600"
    assert notes["nginx.ingress.kubernetes.io/proxy-buffering"] == "off"


def test_app_urls_are_in_cluster() -> None:
    data = config_data()
    for app in ("MIWORKBENCH", "MISERVER", "MIDATAWORKS", "MIFORGE"):
        url = data[f"MIASSIST_{app}_URL"]
        assert url == f"http://{app.lower()}-backend.{app.lower()}.svc.cluster.local:8000"


# -- 5.3 - 5.6: Postgres and its backup -------------------------------------------------------


def test_postgres_shape() -> None:
    pg = next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "miassist-postgres")
    assert pg["spec"]["strategy"]["type"] == "Recreate"
    assert pg["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == (
        "Prune=false,Delete=false"
    )
    spec = pg["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"kubernetes.io/hostname": "mcs-lnxhost02"}
    env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
    assert env["PGDATA"] == "/var/lib/postgresql/data/pgdata"
    assert spec["containers"][0]["image"] == "postgres:15"


def test_backup_cronjob() -> None:
    (job,) = of_kind("CronJob")
    spec = job["spec"]
    assert job["metadata"]["name"] == "miassist-db-backup"
    assert spec["schedule"] == "30 4 * * *"
    assert spec["timeZone"] == "America/New_York"
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 14400
    pod = spec["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "mcs-lnxhost02"}
    script = pod["containers"][0]["command"][-1]
    assert 'mv "$partial" "$target"' in script, "publish by rename after verification"
    assert script.index("pg_restore -l") < script.index('mv "$partial" "$target"')
    assert script.index('mv "$partial" "$target"') < script.index("pruning")
    assert "RESTORE.md" in script


def test_storage_and_app_are_not_synced() -> None:
    pv, pvc = docs("storage.yaml")
    assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
    assert pvc["metadata"]["name"] == "miassist-pgdata"
    app = next(d for d in docs("argocd/miassist-app.yaml") if d["kind"] == "Application")
    assert app["spec"]["source"]["repoURL"] == "https://github.com/Onegaishimas/miAssist.git"
    assert app["spec"]["source"]["targetRevision"] == "gitops/pilot"
    assert app["spec"]["source"]["path"] == "gitops/pilot"
    notes = app["metadata"]["annotations"]
    assert notes["argocd-image-updater.argoproj.io/server.update-strategy"] == "digest"


def test_public_base_url_is_the_lan_host() -> None:
    """13.1: the personal link printed by /p/new names the LAN host until push 001-P and the
    public host from it (14.5), and the serving container receives it by key (never envFrom,
    OVN-miassist-core-2)."""
    expected = PUBLIC_HOST if exposure.PUBLIC_HOST_APPROVED else "k8s-miassist.hitsai.local"
    assert config_data()["MIASSIST_PUBLIC_BASE_URL"] == f"https://{expected}"
    server = next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "miassist")
    serving = server["spec"]["template"]["spec"]["containers"][0]
    refs = {
        e["name"]: e["valueFrom"]["configMapKeyRef"]["key"]
        for e in serving["env"]
        if "configMapKeyRef" in e.get("valueFrom", {})
    }
    assert refs["MIASSIST_PUBLIC_BASE_URL"] == "MIASSIST_PUBLIC_BASE_URL"


def test_the_image_updater_pin_file_is_exempt_and_nothing_else(tmp_path: Path) -> None:
    """gitops/pilot carries Image Updater's write-back file; its CI must stay green with it, and a stray
    manifest beside it must still be caught (the exemption is one exact name)."""
    import shutil

    tree = tmp_path / "pilot"
    shutil.copytree(PILOT, tree)
    (tree / ".argocd-source-miassist.yaml").write_text("kustomize:\n  images: []\n")
    assert unlisted_files(tree, listed()) == set()
    (tree / ".argocd-source-other.yaml").write_text("kustomize: {}\n")
    (tree / "stray.yaml").write_text("kind: ConfigMap\n")
    assert unlisted_files(tree, listed()) == {".argocd-source-other.yaml", "stray.yaml"}
