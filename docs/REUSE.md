# Copied code: the origin index

PADR ADR-001. **miAssist imports no code from miWorkbench, miServer, miDataworks or miForge, ever,**
and they import none from it. `tests/unit/test_no_app_imports.py` enforces it, with a self-test
proving the scanner sees every import form.

Reuse therefore means **copying**, and a copy without a recorded origin is a fork nobody knows they
are maintaining. Two rules:

1. **Copied code carries an origin header** in the file itself: repository, path, commit.
2. **Copied code gets a row in the table below.**

| miAssist file | Origin | Commit | Mode |
|---|---|---|---|
| `tests/support/siblings.py` | miForge `backend/tests/support/siblings.py` | e4251e4 | adapt: four siblings, miAssist's switches |
| `.github/scripts/private_ci_gate.py` | miForge `.github/scripts/private_ci_gate.py` | e4251e4 | copy |
| `.github/workflows/backend-tests.yml` | miForge `.github/workflows/backend-tests.yml` | e4251e4 | adapt: one job, Postgres service |
| `.github/workflows/docs-check.yml` | miForge `.github/workflows/docs-check.yml` | e4251e4 | adapt: the reference check only |
| `.github/workflows/manual-ci.yml` | miForge `.github/workflows/manual-ci.yml` | e4251e4 | adapt |
| `.github/workflows/sync-to-clean.yml` | miForge `.github/workflows/sync-to-clean.yml` | e4251e4 | adapt: guards, required list, cassette and docs strip |
| `.github/workflows/sync-main-to-gitops-pilot.yml` | miForge `.github/workflows/sync-main-to-gitops-pilot.yml` | e4251e4 | adapt: names |
| `.github/workflows/docker-images.yml` | miForge `.github/workflows/docker-images.yml` | e4251e4 | adapt: one image |
| `.github/workflows/deploy-manual.yml` | miForge `.github/workflows/deploy-manual.yml` | e4251e4 | adapt: names |
| `gitops/pilot/postgres.yaml` | miForge `gitops/pilot/postgres.yaml` | e4251e4 | adapt |
| `gitops/pilot/argocd/miassist-app.yaml` | miForge `gitops/pilot/argocd/miforge-app.yaml` | e4251e4 | adapt: one image |
| `gitops/pilot/db-backup.yaml` | miDataworks `k8s/base/db-backup.yaml` | 895dde3 | adapt: names, revision-id schema version |
| `tests/support/source_tree.py` | miDataworks `backend/tests/support/source_tree.py` | a94d99bf | adapt: "stripped" by running the strip step, a per-entry form |
| `tests/unit/test_manual_publish_allowlist.py` | miForge `backend/tests/unit/test_manual_publish_allowlist.py` | e4251e4 | adapt: dropped miForge-only checks |
| `src/miassist/installed/detector.py` | miForge `backend/src/mcp_server/health_gate.py` | e4251e4 | adapt: N apps, a fixed-interval loop, probes through each app's client |
| `src/miassist/server/audit.py` | miForge `backend/src/mcp_server/server.py` (`wrap_tool_with_audit`) | e4251e4 | adapt: argument names only, the key as its fingerprint |
| `src/miassist/server/strict_args.py` | miForge `backend/src/mcp_server/server.py` (`_strict_arguments`, `refuse_unknown_arguments`) | e4251e4 | adapt: the suite's one code, `unknown_arguments` |
| `manual/scripts/check-published.mjs`, `manual/scripts/check-published.test.mjs`, `manual/publish-rules.json` | miForge `manual/` | e4251e4 | copy |
