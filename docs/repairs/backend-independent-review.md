# Independent backend repair review — R5 scope B1/B4/B6/B2/B3

October 8, 2026. **PASS for all five reviewed finding IDs on the current fresh-store contract. No new confirmed backend regression.** This reviewer did not author the repairs. This is independent local source/regression verification, not final candidate certification or external provider/container acceptance.

Reviewed the R1/R2/R5 requirements, original backend findings, dispatch controls, repair report, current production/test diff and consumers. The only repository write by this reviewer is this report. Original sources and additional synthetic reproducers were created under `/tmp`; existing production and test files remained unchanged. No real credentials/profile, network provider, SMTP destination, Sheets write, Docker/runtime lifecycle, image, cleanup, commit or deployment was used.

## Independent decision per finding

| Finding | Decision | Mechanism and independently observed result |
| --- | --- | --- |
| B1 — collection ownership/run budgets | **PASS** | `storage.py:129` persists `collection_owner`, `search_runs.py:467` explicitly registers saved-search ownership, and `collection.py:106` admits only registry targets. Forced ordinary collection cannot fetch saved Greenhouse/Lever/Ashby/JobSpy targets after pause/deletion or between scheduled runs. Independent registry collection still works. Saved ingestion retains the transaction checkpoint that inserts `search_run_jobs` before jobs become visible; all-zero and individual zero job/call/token limits remain denied after restart. A separate synthetic Lever reproduction confirmed the original unassociated `new` job/budget bypass, then observed no second fetch or job under the repair. |
| B4 — retry ownership | **PASS** | `queue.py:48` scopes the expiry sweep with the same kinds used by selection. Concurrent email claims at their three-attempt ceiling leave a three-attempt master task running; its five-attempt owner has one concurrent reclaim winner and can reach attempts four/five before its own terminal expiry. The original source instead fails the master task at attempt three. |
| B6 — canonical closure | **PASS** | `storage.py:382` checks every direct observation for the canonical job after incrementing the absent alias. An alias with fewer than two complete authoritative misses, or a direct observation from a search-window target, blocks closure. A present second direct board remains open without an opening-revision increment; closure occurs after that board also disappears twice. Additional tests verify that error-bearing complete results cannot prove absence and non-inventory direct observations keep blocking closure. Existing partial-fetch, timestamp, reopening and stale-aggregator behavior passes. |
| B2 — SMTP outcome/queue atomicity | **PASS** | `queue.py:132` checkpoints inside the caller's transaction with task ID, token, running state and live lease; `email_integrations.py:497` changes task, attempt and delivery outcome together. Terminal accepted/cancelled/uncertain/failed deliveries stop before transport at `:320`. A durable interrupted pending attempt becomes uncertain, including the exhausted final attempt (`:406`). Original accepted/uncertain outcomes survived a queue checkpoint abort and replayed after a post-outcome crash; repaired outcomes roll back or commit together and do not auto-replay. Independent inverse failure injection after the successful queue update also rolled back the task/attempt/delivery together. Same-token lease expiry during transport cannot publish accepted and is recovered as uncertain without a second send. |
| B3 — current email members/content | **PASS** | `email_integrations.py:354` compares each persisted member identity with current profile/model/posting identity and current qualification; `:386` checks open/applied, owner dismissal/rejection, score and recommendation. Invalid members are removed durably, bodies are rebuilt, and empty deliveries are cancelled. The second admission at `:453`, after PDF lookup, removes members changed during that lookup; `:473` filters attachments against the final member set. Separate adversarial mixed-digest evidence changed one member's content hash during its PDF lookup: only the other member's current body/PDF was transported and retained in membership. |

The code continues to use ordinary Python, SQLite, existing model/assessment contracts and the existing queue. Collection performs no inference or delivery. No compatibility adapter or replacement queue was introduced.

## Reconstructed original failures

To verify red evidence without modifying the working source, `/tmp/backend-independent-setup-20261008.py` copied `src/` to `/tmp/backend-independent-original-20261008/src`, then replaced the five owned backend modules with the exact `git show 3239183c8b2de4a6f3227eac9e750ddb5ce8d53c:<path>` bytes. All unrelated imported modules remained the current snapshot. These runs use fresh synthetic stores; they are targeted reconstruction of the original backend failures, not a claim to execute the entire historical release.

```sh
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python /tmp/backend-independent-setup-20261008.py
rtk proxy env PYTHONPATH=/tmp/backend-independent-original-20261008/src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_search_runs.py::test_registry_collector_never_owns_saved_sources tests/test_queue.py::test_foreign_worker_cannot_exhaust_master_retry_policy tests/test_storage.py::test_closure_requires_all_direct_aliases_to_disappear --basetemp=/tmp/backend-independent-r1-red-20261008 --tb=short
```

**11 failed, 3 passed in 1.44s.** Nine Lever/Ashby/JobSpy state cases performed the prohibited second ordinary fetch. The foreign queue failed master work at attempt three, and one absent direct alias closed a job whose other direct alias remained present. Three Greenhouse controls passed under the original provider-specific exclusion. These were the intended defect assertions, not import/setup failures.

```sh
rtk proxy env PYTHONPATH=/tmp/backend-independent-original-20261008/src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_email_integrations.py::test_delivery_outcome_and_queue_checkpoint_rollback_together tests/test_email_integrations.py::test_crash_after_outcome_commit_cannot_replay_transport tests/test_email_integrations.py::test_terminal_delivery_admission_never_calls_transport tests/test_email_integrations.py::test_queued_members_revalidate_before_transport --basetemp=/tmp/backend-independent-r2-red-20261008 --tb=short
```

**14 failed in 0.96s.** Two checkpoint crashes left accepted/uncertain attempt outcomes committed; two post-outcome crashes produced two transport calls; three terminal delivery states still reached transport; seven profile/model/posting/action changes still sent queued obsolete content.

A separate reviewer-written reproduction exercises the actual Lever pause/budget trigger beyond those retained tests:

```sh
rtk proxy env PYTHONPATH=/tmp/backend-independent-original-20261008/src /tmp/internship-pipeline-audit-venv/bin/python /tmp/backend-independent-b1-repro-20261008.py
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python /tmp/backend-independent-b1-repro-20261008.py
```

Original: `fetches_after_pause=1`, `ordinary_new_jobs=1`, `total_jobs=2`, `leaked_job_event=new`, `leaked_job_has_run=false`, and `reserve(..., 'assessment', 999999)` returned `None`, allowing work outside the zero run budgets. Repaired: `fetches_after_pause=0`, `ordinary_new_jobs=0`, `total_jobs=1`.

## Current verification

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_collection.py tests/test_queue.py tests/test_storage.py tests/test_search_runs.py tests/test_normalization.py tests/test_assessments.py tests/test_generation_policy.py tests/test_email_integrations.py tests/test_master_resume.py tests/test_tailored_resume.py --basetemp=/tmp/backend-independent-adjacent-20261008-v2 --tb=short
```

**198 passed in 16.60s.** This verifies the retained failure regressions and adjacent ordinary collection, run association/admission, retry ceilings, canonical lifecycle, current assessment identity, automatic generation, master/tailored documents and email success/rejection/cancellation/explicit retry. The repair report's earlier 195 count predates its final three email controls; the current 198 includes them. An earlier equivalent reviewer run completed, but its completion output was omitted by a batched tool output limit, so the recorded evidence is the explicit `v2` rerun above.

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_email_integrations.py --basetemp=/tmp/backend-independent-email-20261008-v1 --tb=short
rtk proxy env PYTHONPATH=src:tests /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q /tmp/test_backend_independent_20261008.py --basetemp=/tmp/backend-independent-adversarial-20261008-v1 --tb=short
```

**35 email tests passed in 2.02s**, overlapping the 198; counts must not be summed. **Six additional reviewer-written adversarial tests passed in 0.37s**. They verify expired/live/wrong-token/already-terminal checkpoint fencing, rollback after a successful checkpoint, inverse outcome-transaction failure, same-token lease expiry during SMTP, mixed digest/PDF staleness during lookup, error-bearing inventory and direct search-window authority. The `/tmp` tests import only synthetic fixture helpers and use scoped transports; they do not replace or alter the retained tests. Runs emitted the existing Starlette TestClient deprecation warning and no skips.

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/collection.py src/internship_pipeline/queue.py src/internship_pipeline/storage.py src/internship_pipeline/search_runs.py src/internship_pipeline/email_integrations.py tests/test_collection.py tests/test_queue.py tests/test_storage.py tests/test_search_runs.py tests/test_email_integrations.py
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m mypy --strict src/internship_pipeline/collection.py src/internship_pipeline/queue.py src/internship_pipeline/storage.py src/internship_pipeline/search_runs.py src/internship_pipeline/email_integrations.py
rtk proxy git diff --check -- src/internship_pipeline/collection.py src/internship_pipeline/search_runs.py src/internship_pipeline/storage.py src/internship_pipeline/queue.py src/internship_pipeline/email_integrations.py tests/test_search_runs.py tests/test_storage.py tests/test_queue.py tests/test_email_integrations.py
```

Ruff passed, strict mypy reported no issues in all five source files, and the scoped diff whitespace check passed.

## Crash boundaries and consumer interactions

Before transport admission commits, termination rolls back the attempt; a later worker may safely admit one send. After the pending attempt commits but before transport, termination conservatively requires explicit retry even if no message was actually sent. During transport or after an external accepted result but before the outcome commit, remote acceptance cannot be determined from SQLite: recovery surfaces uncertainty and does not resend automatically. During the outcome transaction, either all three records commit or all roll back. After commit, accepted/done and uncertain/failed states remain terminal. Failed credentials do not call SMTP and require explicit retry; definite rejection retains the bounded backoff policy. Owner retry deliberately resets failed/uncertain work and settles pending attempts; cancelling settings stops queued/retrying work. These are controlled-attempt guarantees, not SMTP exactly-once delivery.

CLI and app PDF consumers (`cli.py:159`, `app.py:372`) obtain `TailoredResumes.latest()` and call `pdf()` only when downloadable; `resumes/tailored.py:237` rejects a stale document key. Email admission then checks assessment/member identity again and filters already-read PDFs to final eligible job IDs. Changes after transport admission cannot retract a message already handed to transport; the reviewed guarantee is qualification at the committed admission boundary.

Saved-search pause prevents new scheduled/manual admission; explicit run cancellation/deletion retains its existing separate behavior. Already admitted work preserves run associations. Registry source identity remains independent, and no new external fetch is introduced by the ordinary collector for saved targets. Target ownership uses the fresh explicit schema; **older databases without `collection_owner` are unsupported by these checks**. No migration/fallback was demanded or added, in accordance with the user's no-backward-compatibility requirement. This pass is not an older-data upgrade claim.

## Tested identity and remaining release gates

The reviewed lane remains an uncommitted working diff against HEAD `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`, alongside concurrent web/security and operations changes. Backend byte identity captured after the verification:

| File | SHA-256 |
| --- | --- |
| `src/internship_pipeline/collection.py` | `95c22ceccb22276eb937c3dca5ed05ab7e43aa37c605aaa7735cbd8e1f8a88ba` |
| `src/internship_pipeline/search_runs.py` | `bf7209ddb31b6e8780a84c68df2bf954b2f25d7d51acbc2be497b19638571aa7` |
| `src/internship_pipeline/storage.py` | `07cf829cde5743fb202e3f23d2dd1514c48adf624d23546c4f0b4c08a9166b6d` |
| `src/internship_pipeline/queue.py` | `99302cf39281714a0274f10b00ea9d2f7ccf4333cfd8cabe589985da662812e7` |
| `src/internship_pipeline/email_integrations.py` | `4371bd91522358f535f590317a49bf83f8806ace3cb887fc344877987009ca4a` |
| `tests/test_search_runs.py` | `b9e8fe473a75939d7f524e2043a7c8de74c37f94efdcf1781fda36f860cc1e97` |
| `tests/test_storage.py` | `93529c368c8e48af6853d856f0187803bfed89d3d6ce3bceffda59c7af6125f7` |
| `tests/test_queue.py` | `e598ef306118f7d8f9c752184c1b7518e37cf0dce39a064c125d3fd7606b6e83` |
| `tests/test_email_integrations.py` | `34f1db2b11dffe824cf716f77702ad421acd5994bf54de21dcae46923567e19b` |

No new prioritized finding or minimal fix request is required for these five IDs. Their independent backend sign-off can be recorded by the integration owner. Full combined Python/static/frontend/browser/accessibility validation, all remaining finding IDs and frozen candidate identity still belong to the broader R5 acceptance. R6–R9 real image/runtime/recovery, live bounded providers/SMTP/Sheets, distribution/licensing and hosted installation gates remain distinct and unverified here. A later change to the reviewed bytes requires affected re-verification.
