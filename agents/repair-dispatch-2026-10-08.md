# Repair dispatch and regression controls

October 8, 2026. Execute [release-repair-subtasks.md](release-repair-subtasks.md), starting with the sixteen confirmed defects. This file defines the pre-dispatch controls. **Completion update:** [combined verification](../docs/repairs/combined-verification.md) records R1–R5 native/synthetic closure, source identity and independent review; R6–R9 external acceptance remains open. GitHub Actions was selected and prepared for the next image gate, without push or dispatch.

## Starting snapshot

Source HEAD: `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`. Existing working changes at dispatch are the release plan and its pointer in `docs/release-readiness.md`; preserve them. The parent runs the current complete Python regression suite before agents begin production edits. Historical 525-test and installer/management counts are not substituted for that result.

**Recorded baseline:** 608 Python tests passed in 65.84 seconds, with one existing Starlette TestClient deprecation warning, before repair-worker dispatch. Command: `rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q --basetemp=/tmp/pipeline-repair-baseline-20261008-6f92c1 --tb=short`. Approved local-only process/server access was used. This is a regression baseline, not proof that the sixteen known defects are fixed.

## Ownership and order

| Worker | Findings | Owns | Required sequence |
| --- | --- | --- | --- |
| `repair_backend_high` | B1, B4, B6, then B2, B3 | Collection/search-run ownership, queue expiry/checkpoint APIs, source closure in storage, email backend and corresponding tests | Reproduce R1 failures → repair collection/queue/closure → adjacent tests → R2 SMTP outcome/admission repairs → crash/digest/restart tests |
| `repair_web_security_high` | W1–W6 | Svelte editor/navigation/jobs state, anonymous session admission in app/identity, browser and authentication tests | Reproduce unsafe revision conflict first → repair draft revision/state → session admission and remaining UI fixes → integrated two-context/browser/auth checks |
| `repair_data_operations_high` | B5, O1–O4 | Sheets export backend, operations backup/verification, installer runtime/log helper, shipped deployment configuration, recovery docs and corresponding tests | Reproduce export/backup failures → repair completeness and database identity → logs/config/recovery repairs → large-inventory and complete-restore regressions |

No concurrent edits to a shared module without agreement. Backend owns `queue.py` and `storage.py`; other workers request the specific shared change. Web owns `app.py` session handling; if exports need an HTTP response change, data/operations sends the exact contract and web mounts it. Web owns `SheetsSettings.svelte`, while data/operations owns export behavior in `sheets_integration.py`; neither changes the other's revision contracts silently. Data/operations owns deployment docs/runtime helpers. The parent owns the plan, defect ledger and aggregate verification.

## Tests before changes

1. Recreate each review's trigger in a durable synthetic test, run it against the current implementation and record the actual defect assertion that fails. Collection/import/setup failures are not proof of the intended red test.
2. Repair the underlying contract, then run that regression and adjacent existing tests. Do not remove assertions, raise unrelated budgets, auto-skip a failure, loosen authorization/locks, or replace a real integration boundary with a mock merely to turn the suite green.
3. Cover the unaffected behavior too: registry collection, normal session reuse/login, successful settings saves, manual generation, source timestamps, independent retry ceilings, intentional owner retries, CSV formula protection, current backup keys/documents and sanitized log output.
4. Use scoped monkeypatches and isolated temporary directories; never overwrite shared test data or patch a provider globally across tests. Use a unique pytest `--basetemp` per worker/run. The space-free interpreter in the prior acceptance handoff avoids executable-fixture shebang path issues.
5. Web worker owns frontend builds and browser ports. Others coordinate before any browser suite so a concurrent build or fixture cleanup cannot corrupt another run. Dedicated Playwright suites retain their distinct fixtures/output locations.

Specific required edge tests remain in the main plan: paused/deleted sources with zero budgets, mixed-kind lease expiry, multi-source closure, accepted/uncertain SMTP crash windows, stale digest members, two-browser-context configuration conflicts, persistent concurrent anonymous-session admission, all dirty settings categories, malformed URLs/mobile history, 10,001+ export rows, reserved-character backup paths/wrong database identity, stderr redaction and exclusive offline recovery.

## Handoff and independent closure

Each worker writes only its own `docs/repairs/<lane>.md` with finding IDs, red/green evidence, files changed, existing test results, runtime assumptions and unresolved scope. A worker may report **implemented and locally verified**, but independent closure remains R5.

After all three lanes settle, the parent/review stage checks the combined diff, independently reruns each original reproduction, runs the complete current Python suite (including installer/manager), Ruff, strict mypy, Svelte check/build, default and affected dedicated browser suites. Failures return to the owning lane; a test-count total is not a substitute for defect-specific evidence. Record the final tested source identity and uncommitted diff state.

## Limits and later release work

No commits, pushes, runtime start/reset/prune, disk cleanup, image builds, private profile/credential reads, paid calls, external messages, remote-sheet writes or publication are included in this repair dispatch. All provider responses and destinations are synthetic. Preserve historical reviews/evaluation reports.

R5 independent verification follows these repairs. R6–R9 remain staged behind the repaired candidate and their explicit external inputs: healthy build capacity, bounded authorized provider tests, license/distribution decisions and real hosted installation evidence. No finding or release gate is marked complete because an agent stops working.
