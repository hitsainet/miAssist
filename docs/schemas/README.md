# Schemas

The contracts miAssist owns and the copies it vendors (PADR ADR-008). Every file in this directory
has a row here and an entry in `tests/contract/schema_ownership.py`; a file with neither fails the
schema-sync test.

- **owned**: generated from Pydantic models in `src/miassist/contracts/` by `scripts/write_contracts.py`,
  never hand-edited; the sync test regenerates and compares bytes. Consumers vendor a byte-identical copy
  (push order: miAssist first).
- **vendored**: a byte-identical copy of a sibling's published file, compared by a cross-repo test.

| File | Ownership | Owner | Notes |
|---|---|---|---|
| `mistudio-result-language-v1.json` | owned | miAssist | `mistudio.result-language/v1`; vendored byte-identical by miWorkbench, miDataworks and miForge |
| `mistudio-playbook-v1.json` | owned | miAssist | `mistudio.playbook/v1`; every definition under `src/miassist/playbooks/definitions/` validates against it (Core's start-here playbooks; 003-005 add theirs) |
| `next-tool-hints.json` | vendored | miServer | byte copy of `miServer/docs/schemas/next-tool-hints.json` (copied at 3309a0f1, 15 names: 043 added `miserver_arm_probe`; first copied at 04ac4524 with 14); every name maps in `src/miassist/guidance/miserver_next.yaml` |
| `miserver-answers-v1.json` | vendored | miServer 044 | byte copy of miServer's answer contract (`miserver.answer-contract/v1`), copied at 05672754, revision 2 (first copied at 4a09a469, revision 1); 182 typed responses, 2 excluded, errors `management` and `openai`, 4 external `$id`s read as open objects; miServer's answer shapes are read from it (ENH-013 006-1) |
| `miworkbench-approval-payload-vectors-v1.json` | vendored | miWorkbench 045 | byte copy of miWorkbench's per-route approval payload vectors (copied at fdb53989a on `mcpux/045-A0`, 56 vectors; first copied at d458c9195 with 53; push 001-V); `canonical_payload()` reproduces every vector |

**Siblings' answer contracts (ENH-013 006, open debt until 006-4).** Each sibling's
`docs/schemas/<app>-answers-v1.json` is vendored here, byte-identical, as each is published; the row says `copied at
<commit>, revision <n>`. Until an app is vendored its answer shapes are hand records in
`tests/fixtures/openapi/responses.json` (on 2026-11-25: miServer 18, miDataworks 34, miWorkbench 44, miForge 7, and miForge 9 after main's
`2f541bf` of 2026-11-27; `tests/contract/test_hand_records.py`). Vendored: miServer (006-1).

Not in this directory, on purpose: the cassette format is a TEST contract between Core and 002 (its schema is
generated from `tests/support/cassette.py` into `tests/fixtures/`; this published page does not spell its name, or the
mirror's fail-closed strip refuses it, OVN-miassist-core-31).
