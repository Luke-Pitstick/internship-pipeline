# Backend repair evidence — R1 and R2

October 8, 2026. Status: **implemented and locally verified; independent R5 review pending**.
Starting HEAD: `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`. Evidence below describes this lane's working changes, alongside concurrent web/security and data/operations work. No commit, image, deployment, live SMTP or paid provider acceptance is claimed.

## Repairs and retained regressions

| Finding | Implementation | Regression evidence |
| --- | --- | --- |
| B1 | Persist `targets.collection_owner`; saved-search runs explicitly own their targets, and the ordinary collector selects registry ownership. Remove the obsolete Greenhouse ID exclusion. Saved-search ingestion retains its existing atomic run membership/budget checkpoint. | All four saved-source types stay out of ordinary collection after pause/deletion or between scheduled runs, even under forced collection; a mocked extra posting cannot enter without run membership. Independent registry sources still collect. All-zero and individual zero job/call/token budgets remain denied after restart. |
| B4 | Filter the expiry sweep by the claiming worker's task kinds before applying its attempt ceiling. | Concurrent email claims exhaust email work at three attempts while master work survives and is reclaimed under its five-attempt policy; concurrent master claims have one winner. |
| B6 | After complete direct-board absence evidence, examine every direct observation of the canonical job before closing it. A still-present direct alias or an observation without full-inventory authority blocks canonical closure. | The first alias disappears twice while a second remains present: status stays open and opening revision stays zero. Partial scans remain safe; closure occurs only after the second direct alias also misses two complete inventories. Existing stale-aggregator, reopening and timestamp assertions remain. |
| B2 | Add `Queue.checkpoint(connection, task, status, error)` to transition queue state inside the delivery outcome transaction, fenced by task token, running state and live lease. Admission recognizes accepted/cancelled/uncertain/failed outcomes; interrupted transport attempts become uncertain, including the final exhausted attempt. | Crash injection before/after admission and outcome commits, checkpoint transaction rollback, terminal admission and lost leases prevent automatic replay. Accepted outcome and done task commit together; an uncheckpointed external outcome remains uncertain and requires explicit owner retry. Existing successful/rejected/uncertain flows and retry ceiling remain intact; unreadable credentials fail visibly and need explicit retry. SMTP exactly-once acceptance is not promised. |
| B3 | Reuse current qualification at enqueue and transport admission; compare each member's assessment identity, current score/recommendation and open/applied/owner state. Prune stale members, rebuild durable digest bodies, cancel empty deliveries and revalidate after PDF lookup. | Profile/model/posting changes, dismissal, rejection, closure, applying, threshold failure and non-recommended assessments suppress queued content. Mixed digests retain only eligible members/PDFs. A member changed during PDF lookup cancels before transport. Existing timestamp wording and explicit applied tracking remain intact. |

Owned production files: `collection.py`, `search_runs.py`, `storage.py`, `queue.py`, `email_integrations.py`. Owned regression additions: `tests/test_search_runs.py`, `tests/test_storage.py`, `tests/test_queue.py`, `tests/test_email_integrations.py`. `run_limits.py` required no change because the existing ingestion checkpoint already associates admitted saved-search jobs atomically.

The current target schema adds the explicit ownership field. No legacy-schema migration or fallback is provided, consistent with the requested removal of backward-compatibility paths. Tests create fresh isolated stores; existing deployed databases with an older target schema were not exercised.

## Red evidence before production fixes

R1 command:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_search_runs.py::test_registry_collector_never_owns_saved_sources tests/test_queue.py::test_foreign_worker_cannot_exhaust_master_retry_policy tests/test_storage.py::test_closure_requires_all_direct_aliases_to_disappear --basetemp=/tmp/backend-r1-red-final-20261008 --tb=short
```

**11 failed, 3 passed in 1.74s.** Nine Lever/Ashby/JobSpy cases fetched twice despite the saved-source state; the unrelated email claimant failed master work at attempt three; the canonical job became closed while its Lever alias remained present. The three Greenhouse controls passed under the old provider-specific exclusion. Earlier fixture-construction errors were corrected before this valid red run and are not counted as defect evidence.

R2 command:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_email_integrations.py::test_delivery_outcome_and_queue_checkpoint_rollback_together tests/test_email_integrations.py::test_crash_after_outcome_commit_cannot_replay_transport tests/test_email_integrations.py::test_terminal_delivery_admission_never_calls_transport tests/test_email_integrations.py::test_queued_members_revalidate_before_transport --basetemp=/tmp/backend-r2-red-20261008 --tb=short
```

**14 failed in 1.20s.** Attempt outcomes stayed accepted/uncertain after a task checkpoint failed; accepted and uncertain post-commit crashes produced two transport calls; terminal outcomes and seven current-state changes still called transport. These are actual defect assertions, with SQLite/transport setup completing normally.

## Green verification

R1 focused and adjacent suite:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_collection.py tests/test_queue.py tests/test_storage.py tests/test_search_runs.py tests/test_normalization.py tests/test_generation_policy.py tests/test_assessments.py --basetemp=/tmp/backend-r1-green-20261008 --tb=short
```

**121 passed in 8.50s**, before the additional individual-zero-budget and concurrent-claim controls.

Combined backend adjacent suite, including those additional R1 controls:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_collection.py tests/test_queue.py tests/test_storage.py tests/test_search_runs.py tests/test_normalization.py tests/test_assessments.py tests/test_generation_policy.py tests/test_email_integrations.py tests/test_master_resume.py tests/test_tailored_resume.py --basetemp=/tmp/backend-final-adjacent-valid-20261008 --tb=short
```

**195 passed in 18.40s.** Afterwards, three further email controls were added without production changes: credential failure/explicit retry, unknown outcome and transport exception. The final email suite is **35 passed in 1.85s**:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_email_integrations.py --basetemp=/tmp/backend-r2-final-extra-20261008 --tb=short
```

Counts overlap and must not be summed. These suites emitted one existing Starlette TestClient deprecation warning. All fixtures are synthetic; provider/SMTP responses are scoped offline mocks, and pytest roots are isolated per run.

Scoped Ruff: **all checks passed**, after final tests:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/collection.py src/internship_pipeline/queue.py src/internship_pipeline/storage.py src/internship_pipeline/search_runs.py src/internship_pipeline/email_integrations.py tests/test_collection.py tests/test_queue.py tests/test_storage.py tests/test_search_runs.py tests/test_email_integrations.py
```

Strict mypy: **no issues in five source files**:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m mypy --strict src/internship_pipeline/collection.py src/internship_pipeline/queue.py src/internship_pipeline/storage.py src/internship_pipeline/search_runs.py src/internship_pipeline/email_integrations.py
```

`rtk git diff --check` passed at the lane handoff. Production changes have settled; the parent owns combined-suite/browser verification, the defect ledger and independent sign-off. Live SMTP/model capability, real container/restart/recovery, supported architectures, release publication and the remaining release gates retain their separately stated external evidence requirements.
