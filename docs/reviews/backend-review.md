# Backend implementation review — T01–T20

Reviewed October 7, 2026, against HEAD `e9f4c012ef3c14f709abe7a20ab416fdebff13c2` and the current working tree. This is an independent review of the full backend implementation, not a review confined to the latest diff. No production code, tests, dependencies, real profiles, credentials, or historical reports were changed. No provider request, email, Google Sheets mutation, container, deployment, or background application runtime was started. The only repository write is this report.

The backend has useful separation between collection, authoritative assessments, document generation and delivery, but six demonstrated correctness bugs remain. Two affect control over external work and SMTP replay. Passing regression tests do not cover these reproduced failure windows.

## Confirmed findings

### B1 — P1: Saved-search pause, schedules and zero budgets are bypassed by the other collector

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/collection.py:106–111`.

`SearchRuns.process_next()` registers browser-owned Lever, Ashby and JobSpy targets in the shared `targets` table. The ordinary `collect_due()` collector excludes only `company:browser-greenhouse-*`; it subsequently polls the other browser-owned targets using its own persisted due times. Pausing or deleting a saved search modifies `saved_searches`/`search_runs`, not these targets. If the collector role is active—for example, when the installation also has valid company/search registry files—the saved search continues fetching outside its schedule and after pause/deletion.

This also bypasses its model admission limits: jobs first discovered by this second collector have no `search_run_jobs` association, and `run_limits.reserve()` admits them without a run reservation when `latest_run()` returns `None`. They can enter matching and optional generation despite a saved search whose jobs/calls/tokens ceilings are all zero. The independent global Jev limits still apply; the configured run budget and pause control do not.

**Offline evidence:** A temporary SQLite store saved a Lever search with all three ceilings set to zero, ran one mocked collection, paused it, and then invoked the actual `collect_due()` with a mocked ATS connector returning a second posting. The second fetch occurred, the new posting had `event='new'`, `latest_run()` returned `None`, and `reserve(..., 'assessment', 999999)` admitted it by returning `None`. A simpler version fetched the same paused search twice while history still contained only one run. No HTTP call occurred.

**Minimal fix direction:** Give browser saved searches one collection owner. Exclude all browser-managed targets from the registry collector using explicit ownership rather than the obsolete single-provider name check, and retain run association for all work the saved-search worker admits. Remove the stale T07 path instead of adding more per-provider fallbacks.

**Confidence:** High. Reproducers: `/tmp/backend_review_repros.py` (`browser_pause`) and `/tmp/backend_paused_budget_repro.py`.

### B2 — P1: A crash after the SMTP outcome checkpoint automatically sends an accepted or uncertain delivery again

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/email_integrations.py:428–446`; recovery admission at `:361–383`.

The transaction stores a completed email attempt and delivery outcome, then a separate transaction completes/fails the queue task. A worker termination between those commits leaves an `accepted` or `uncertain` delivery with a reclaimable running task. On recovery, `process_next()` only checks for a still-pending attempt; a completed accepted/uncertain attempt falls through to a new SMTP attempt. It never checks the delivery's terminal outcome before sending.

An accepted delivery is duplicated, and an uncertain delivery is replayed without the explicit owner action that the implementation promises. This is an avoidable local checkpoint bug; it is separate from SMTP's unavoidable inability to guarantee exactly-once remote acceptance.

**Offline evidence:** The existing synthetic email fixture used a recording transport returning `accepted`. Replacing `queue.complete()` with an injected crash after the outcome transaction left `email_deliveries.status='accepted'` and one send. After setting the expired lease and calling `process_next()` again, there were two sends. The same experiment returning `uncertain` and crashing at `queue.needs_attention()` also produced two automatic sends. Neither case invoked SMTP.

**Minimal fix direction:** Commit the delivery outcome, attempt completion, and terminal/retry queue state in the same fenced SQLite transaction. At claim admission, recognize already accepted/cancelled/uncertain deliveries and finish or require attention without transport I/O. Preserve explicit retry as the only way to replay an uncertain delivery.

**Confidence:** High. Reproducers: `/tmp/backend_review_repros.py` (`email_ack_crash`) and `/tmp/backend_unknown_email_repro.py`.

### B3 — P2: Queued email sends obsolete scores and ignored jobs after profile or review changes

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/email_integrations.py:384–389`, `:403–405`.

Enqueueing checks the current assessment, score threshold, applied state, dismissal and rejection, but the consumer only rechecks email configuration. It retrieves job IDs without checking each member's assessment identity or current review/actionable state, then sends the body created earlier. A profile/model/posting change, dismissal, rejection, closure or mark-applied operation while email is queued therefore does not suppress that stale alert or digest member.

The owner can receive a recommendation they just dismissed, or a score from a profile revision that the dashboard correctly treats as stale. This contradicts the T04 handoff's statement that current worker delivery checks suppress old-profile payloads and the current qualifying-job delivery contract.

**Offline evidence:** Enqueue one synthetic qualifying alert, save profile revision 2, dismiss the job, then process the queue. `stored_view()` reported `state='stale'`, but the recording transport still received the original body and the delivery became `accepted`. No model or SMTP request occurred.

**Minimal fix direction:** Revalidate member identity and qualifying state before transport admission. Cancel a now-empty alert, or rebuild a digest from still-valid members, with durable membership/state changes. Do not send an earlier profile's score while attaching a current-revision draft.

**Confidence:** High. Reproducer: `/tmp/backend_stale_email_repro.py`.

### B4 — P2: A worker's retry ceiling fails expired tasks belonging to other worker kinds

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/queue.py:46–49`.

The lease-expiry sweep in `Queue.claim(kinds)` updates every expired running task in the table using this queue instance's `max_attempts`, without restricting `kind` to `kinds`. Email/Sheets/tailored queues use a ceiling of three, while master résumé work uses the configured ceiling, normally five. An idle email worker can fail a master task after its third interrupted lease even though the master worker still has two recovery attempts available.

This violates independent queue ownership and makes restart behavior depend on which unrelated worker claims first. The master task becomes terminal `failed` and cannot be reclaimed automatically by its own queue.

**Offline evidence:** A temporary store queued one `master_resume` task, claimed/expired it three times under `Queue(max_attempts=5)`, then called `Queue(max_attempts=3).claim(['email_delivery'])` with no email work. The master task became `{status: 'failed', attempts: 3, error: 'LeaseExpired'}`, and the master queue returned `None` on its next claim.

**Minimal fix direction:** Scope expiry transitions to the task kinds owned by the claiming queue, with the same kind filter used for selection. Each kind must be evaluated against its own admission/retry ceiling.

**Confidence:** High. Reproducer: `/tmp/backend_review_repros.py` (`foreign_queue`).

### B5 — P2: CSV and Sheets quietly omit jobs after the 10,000th stable ID

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/sheets_integration.py:248–253`.

`facts()` silently queries only the first 10,000 jobs by ID, and both CSV export and Sheets preview/source fingerprints use that incomplete list. With 10,001 or more jobs, the user receives a successful export/sync that excludes real inventory with no truncation marker or failure. IDs are hashes, so the omitted opportunity is arbitrary; adding a job can also displace an existing job from the exported subset.

The T15 handoff explicitly says larger destinations fail visibly rather than pretending complete coverage. Current CSV export also has no stated reason to truncate the complete local inventory.

**Offline evidence:** A synthetic store with 10,001 persisted jobs returned exactly 10,000 `facts()` rows; the original fixture opportunity disappeared from the exported set. The same routine feeds `csv()` and `preview()`.

**Minimal fix direction:** Detect over-limit inventory explicitly for bounded Sheets plans, and return a clear failure or documented pagination contract. Export the full inventory through a bounded streaming/batching path for CSV. Do not compute a supposedly complete source fingerprint over a silently truncated subset.

**Confidence:** High. Reproducer: `/tmp/backend_review_repros.py` (`local_export_limit`).

### B6 — P2: One disappearing direct-source alias closes an opportunity still present on another direct board

**Location:** `/Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/storage.py:374–382`.

Ingestion deduplicates multiple source observations into one canonical job, but closure is calculated from a single observation's misses. Once that alias misses two full snapshots, the code unconditionally closes the shared job without checking other direct-source observations. If a replacement ATS or another direct board still advertises the same application URL, the canonical opportunity is marked closed even while that other source was just observed.

Subsequent polls of the other board reopen it, so status and `opening_revision` can oscillate as the two pollers run. This suppresses an actionable job and invalidates assessments/artifacts unnecessarily. A stale aggregator must still be unable to reopen a genuinely closed authoritative posting; checking live direct aliases should preserve that existing safeguard.

**Offline evidence:** Ingest two direct observations, Greenhouse and Lever, with the same employer/application URL so they share a job. Ingest one complete empty Greenhouse snapshot, refresh the Lever posting, then ingest the second complete empty Greenhouse snapshot. The shared job became `closed` despite the fresh Lever observation. No connector or HTTP request was used.

**Minimal fix direction:** Compute canonical closure from the authoritative direct-source observations for that job, rather than promoting one alias's absence to a job-wide closure. Keep source/window authority explicit so aggregator presence cannot establish reopening.

**Confidence:** High. Reproducer: `/tmp/backend_review_repros.py` (`alias_closure`).

## Coverage and verification

I read the repository instructions, RTK instructions, current open-source plan, task breakdown, historical implementation checklist and relevant T02/T04/T05/T06/T07/T08/T09/T10/T11/T12/T13/T14/T15 handoffs. Review traced the current queue, collection/source adapters, URL/material revision normalization, SQLite persistence, run admission, profile/import provenance, authoritative assessment request/validation/cache, connection revisions/test budgets, master/tailored generation, policy admission, SMTP delivery and Sheets planning/journals/inward review. The T02 evaluator's split preflight and disabled rejection gate were reviewed separately. Server/API handlers were read where needed to follow these flows, while detailed HTTP/auth/upload-boundary and UI findings belong to the other review owner.

Verified properties include short `BEGIN IMMEDIATE` admission transactions; source versus observation versus delivery timestamp separation; current assessment identities including posting/opening/profile/model/rubric revisions; review-only model violations; conservative unknown-usage reservation accounting; exact source excerpts and atomic import/profile provenance; confirmed-ID-only model selection; escaped application-owned TeX; revision/lease checks when publishing tailored artifacts; and Sheets cell ownership/journals plus explicit inward acceptance. These are reviewed mechanisms and focused test results, not a claim of complete release acceptance.

Reproduced commands:

```sh
rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_storage.py tests/test_normalization.py tests/test_collection.py tests/test_search_runs.py tests/test_assessments.py tests/test_model_connections.py tests/test_profile_settings.py tests/test_resume_import.py tests/test_master_resume.py tests/test_tailored_resume.py tests/test_generation_policy.py tests/test_email_integrations.py tests/test_sheets_integration.py
# 236 passed, one Starlette TestClient deprecation warning, 24.80 seconds.
rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_jev_evaluation.py
# 24 passed, 0.24 seconds.
rtk proxy env PYTHONPATH=src:tests .venv/bin/python /tmp/backend_review_repros.py
rtk proxy env PYTHONPATH=src .venv/bin/python /tmp/backend_paused_budget_repro.py
rtk proxy env PYTHONPATH=src:tests .venv/bin/python /tmp/backend_unknown_email_repro.py
rtk proxy env PYTHONPATH=src:tests .venv/bin/python /tmp/backend_stale_email_repro.py
```

All fixtures were synthetic. The mocked fixture helpers are existing tests, including their synthetic credentials. Reproducers live in temporary paths only and create/delete their own SQLite stores and keys. Regression runs used offline HTTP/transport mocks and the local compiler; they did not contact real providers. No new regression tests were committed because this assignment is review-only.

## Acceptance gaps and non-bug quality observations

- **T02 calibration remains a declared gate.** The current evaluator rejects duplicate tuning/evaluation request bodies before credential loading. Historical synthetic metrics and 24 passing evaluator tests do not establish fresh human-adjudicated calibration. Automatic rejection remains disabled in production, so missing independent quality evidence is an acceptance limitation, not a demonstrated runtime rejection bug.
- **T05/T12/T14/T15 live acceptance was not repeated.** T06 records one earlier synthetic live Jev capability probe; this review independently checked its code path with mocked transport only. General-LLM generation, live SMTP, live Google Sheets, real image/runtime recovery and supported-architecture acceptance remain externally unverified as declared by their handoffs. Credential absence is not scored as an implementation defect.
- **T12 narrows the original output requirement.** The original plan asks the general LLM to draft structured document content, while the current provider returns an ordered list of confirmed fact IDs and preserves wording verbatim. The handoff openly documents this choice and its grounding advantage. The product/spec owner should explicitly accept that reduced content contract or keep prose drafting as an open requirement; it is not a hidden hallucination/factuality bug.
- **T13 owner review decisions need an explicit policy contract.** `generation_policy.qualifies()` uses the stored Jev result and ignores workspace dismissal/rejection/overrides. Unlike email enqueueing, dismissing a high-fit job does not stop automatic draft eligibility. The task's stated policy rules do not explicitly define that interaction, so this is a product-policy ambiguity rather than an additional confirmed finding. Clarify whether owner rejection/dismissal vetoes paid automatic generation, then test that contract.
- **Sheets capacity costs are not established.** For every planned row, the worker rereads the entire bounded values range, requests formula metadata, writes even unchanged desired cells, and rereads the entire values range. The journal/conflict protection is useful, but this is quadratic transferred inventory as job count grows. The suite proves small synthetic behavior, not 10,000-row Google throughput. Prefer batching/reusing snapshots or planning only changed cells while preserving the documented remote concurrency limits; measure the actual supported capacity before promising it.
- **No backward-compatibility layer is recommended.** The collector ownership defect should remove the obsolete T07-specific exclusion, and existing module boundaries/SQLite should be retained. I did not recommend cloud infrastructure, a new queue, RLS, or generic provider abstractions for this single-user product.

**Unreviewed limits:** frontend interaction/accessibility, complete auth/origin/upload sandbox boundaries, installer/management, backup/restore, container/image/deployment and redistribution are assigned to peer reviews. No new live-provider, browser, operational or release claims are made here. Provider protocol correctness was assessed against repository code/types and mocked contracts; externally hosted APIs were not exercised.

Memory was used only to locate the prior task boundaries and known acceptance caveats; findings above were independently verified against current files and synthetic reproductions. Relevant registry context: `MEMORY.md:49–50`, rollout `01a111e2-9978-7fe1-ad48-fac73016e77b`.
