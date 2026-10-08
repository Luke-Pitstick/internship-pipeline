# R3 web and session repair evidence

October 8, 2026. Status: **implemented and locally verified; independent closure belongs to R5**. Starting HEAD was `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`; this evidence describes the shared uncommitted repair candidate, not a released image. The parent recorded the pre-edit Python baseline as 608 passing tests in 65.84 seconds.

## Defect regressions and repairs

The durable browser regressions are in `web/tests/web-security.spec.ts`, served through the isolated real FastAPI/SQLite fixture `web/tests/web-security-serve.py` on port 4187. Two-tab tests use independent browser contexts with independently authenticated owner sessions. Only external Google/model transports and explicitly identified failure responses are synthetic; configuration reads, revision comparisons, saves, owner authorization and SQLite persistence are real.

| Finding | Actual pre-repair failure | Repair and passing evidence |
| --- | --- | --- |
| W1 | Two-context email test waited for tab A's actual poll after B disabled delivery. A's stale save returned **200 instead of 409**. | Email and Sheets keep `draftRevision` separate from polled summaries. Both independent-context tests now get 409, preserve B's disabled email/recipient or mapping, and resolve only through explicit reload. |
| W2 | Saving then reopening Sheets left the Spreadsheet ID **empty instead of synthetic-sheet-id**. | Clone `$state.snapshot(data.config)` through the supported Svelte boundary. Reopen, populated tab/mapping, edit/save and reload all pass. |
| W3 | A 35-request cookie-free burst admitted all callers; concurrent 32-request test admitted **32 instead of 20**. | Persistent atomic guest admission, expiry cleanup, per-address/global windows and active cap. Native concurrency/restart/cap/reuse tests and a real concurrent HTTP burst with varying untrusted forwarded headers pass. |
| W4 | Each AI, source, generation, email and Sheets draft was **reset instead of retaining its edited value** on category return. The models setup step left Continue enabled after editing. | Keep visited editors mounted in memory, report category dirty state, guard route/unload/setup transitions, retain ordinary drafts, provide discard/reload controls, and clear secrets on save/discard. Selected-but-unextracted résumé files now also trigger the existing import guard; its regression first failed because the file input disappeared after navigation. |
| W5 | A real mobile bookmarked `selected` job resolved in the API but the detail aside was **hidden instead of visible**. | Restore explicit URL selection to detail mode and heading focus; selection/closing add history entries, while Back/Forward and Escape restore detail or list focus. The 390×844 viewport has no horizontal overflow. |
| W6 | Malformed `#%E0%A4%A` hash removed the Settings heading and rendered the framework error page. | Guard category decoding and choose Profile for malformed/unknown values. Both routes stay usable. |
| W7, review extension | A's enabled generation draft previewed after B disabled/changed the policy, then stale save returned **200 instead of 409**. | Generation previews update preview/status only; `draftRevision` changes only on load or successful save. Two-context regression preserves B's disabled policy and threshold, then explicit reload resolves it. |
| W8, review extension | A's delayed synthetic model test completed after B saved a newer model, then A's older model save returned **200 instead of 409**. | Maintain a draft revision independently for each provider; capability-test summaries never advance it. The server fixture waits for B's real SQLite revision change before releasing A's synthetic probe. The stale save conflicts, B's model survives and explicit model reload populates it. |
| W9, review extension | Holding an admitted email save left Reload **enabled instead of disabled**, allowing its draft to be replaced while the save was pending. | Disable reload during the save, matching Sheets and other editors. The held-request regression passes and the intended recipient survives. |
| W10, review extension | After accepting discard, an injected visit 409 retained the source draft but left Continue **enabled instead of disabled**. | `visit()` clears dirty state only when the step change succeeds. Failed transitions retain the draft and guard; in-flight setup controls cannot accept new edits. |

Initial server permission, fixture selector, duplicate-title and nested-router lookup failures were corrected and are excluded from defect-red evidence. Existing assertions were retained. The existing mobile assessment test now explicitly asserts that reload restores the bookmarked detail before checking its error/attempt content, matching W5's intended behavior.

## Session limits and persistence

`identity.py` admits at most **20 new anonymous sessions per transport address per 300 seconds**, **100 globally per 300 seconds**, and **128 active anonymous sessions**. Guest TTL remains 20 minutes. The window limits prevent a single browser/address or many addresses from producing a burst of rows; the active cap bounds accumulation across windows. These limits fit a single-owner application because valid guest and authenticated owner sessions are reused without allocating a new row or consuming guest admission. They do not restrict ordinary requests made with a valid session.

A `BEGIN IMMEDIATE` transaction cleans expired sessions/admission windows, checks both admission counters and the active guest count, and inserts the session/counters atomically. Denied admission still commits cleanup. Counters and guest rows remain in SQLite across restart. Address keys are hashed; the app uses the transport address and the dedicated fixture mirrors the shipped bootstrap's existing `--no-proxy-headers` behavior. An exhausted window returns 429 with `Retry-After: 300`. Existing claim, CSRF, owner login, rotation, logout, expiration, recovery and private API behavior pass adjacent tests.

No draft or credential is placed in localStorage/sessionStorage. Ordinary drafts and typed credentials live only in mounted component memory, with navigation guards protecting destruction. Save/discard clears typed model keys, SMTP passwords and service-account keys. Failed saves also clear the submitted secret from its field. Successful loads establish the ordinary draft and its expected revision; polling/test/preview status does not change that revision.

## CSV HTTP handoff with R4

R4 supplied complete stable-ID `csv_chunks()` iteration with a read-only SQLite snapshot and explicit Sheets capacity errors. R3 mounted the iterator in the owner-only CSV response, preserving existing headers and middleware behavior. A narrow `CsvResponse` closes the iterator in `finally` after success, transport error or disconnect; `csv_chunks()` explicitly closes its nested facts iterator, so the read connection closes deterministically. The read-only iterator remains safe across sequential thread-pool hops.

`tests/test_csv_stream_response.py` exports a real SQLite inventory above 10,000 rows and compares every returned ID/order with the database. Two ASGI lifecycle regressions inject a socket send error or disconnect after a real row has been read. With the ordinary StreamingResponse, both first failed because the active SQLite reader was still open **before event-loop shutdown**; with explicit cleanup, both pass. Checking after `asyncio.run()` would hide the defect through asynchronous-generator finalization and is deliberately avoided.

## Changed files and ownership

- `src/internship_pipeline/identity.py` and `app.py` implement atomic guest admission and its 429 route response. `tests/test_owner_app.py` retains concurrency/restart/reuse/auth regressions and the streamed API boundary assertion.
- `web/src/lib/components/SettingsWorkspace.svelte`, `AiModelSettings.svelte`, `EmailSettings.svelte`, `SheetsSettings.svelte`, `GenerationPolicySettings.svelte`, `SourceSettings.svelte` and `ResumeImport.svelte` implement draft/revision lifetimes, secret clearing, explicit discard and load/save readiness. `web/src/routes/setup/+page.svelte` handles successful versus rejected step transitions; `web/src/routes/+page.svelte` handles restored mobile URL/history/focus state.
- `src/internship_pipeline/sheets_router.py` mounts and closes the CSV stream. The parent explicitly approved the narrow Generator annotation and `closing(_facts())` lifetime changes in R4's `sheets_integration.py`; R4's snapshot, escaping and capacity behavior is preserved. `tests/test_csv_stream_response.py` checks real inventory completeness and transport lifecycle.
- `web/playwright.web-security.config.ts`, `web/tests/web-security.spec.ts` and `web/tests/web-security-serve.py` isolate the new suite. `web/playwright.config.ts` excludes it from the default fixture, `web/.gitignore` ignores its generated output, and `web/tests/assessments.spec.ts` asserts the intentionally restored detail after mobile reload. This lane writes only this repair report; the parent owns the defect ledger and aggregate release evidence.

## Exact local verification

Python commands ran from the repository root with the space-free audit interpreter and isolated temporary directories:

- Red W3: `rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_owner_app.py -k cookie_free --basetemp=/tmp/pipeline-web-security-red-session --tb=short`: **2 actual defect failures** in 1.07 seconds.
- Red CSV cleanup: `rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_csv_stream_response.py -k transport_exit --basetemp=/tmp/pipeline-web-security-csv-final-red --tb=short`: **2 actual defect failures** in 0.91 seconds while the response temporarily used the original ordinary StreamingResponse.
- Final native: `rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_owner_app.py tests/test_csv_stream_response.py tests/test_profile_settings.py tests/test_onboarding.py tests/test_resume_import.py tests/test_sheets_integration.py --basetemp=/tmp/pipeline-web-security-final-native --tb=short`: **93 passed** in 24.15 seconds, with the existing Starlette TestClient deprecation warning.
- Owned source/tests Ruff: `rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/app.py src/internship_pipeline/identity.py src/internship_pipeline/sheets_router.py src/internship_pipeline/sheets_integration.py tests/test_owner_app.py tests/test_csv_stream_response.py`: passed.
- Source mypy: `rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m mypy src/internship_pipeline/app.py src/internship_pipeline/identity.py src/internship_pipeline/sheets_router.py src/internship_pipeline/sheets_integration.py`: passed for all four files.
- From `web/`, `rtk npm run check`: **0 errors and 0 warnings**. `rtk npm run build`: passed. `rtk git diff --check`: passed.

Initial original-browser reds used `rtk proxy npx playwright test --config playwright.web-security.config.ts` and focused `-g W2`, `-g 'W4|W6'`, and `-g 'W4 setup|W5'` selections before their respective edits. W7's original focused `-g W7` reproduced the unsafe 200. When the cached Chromium executable became unavailable, subsequent W8/W9/W10 red and final green runs used installed **headless Google Chrome 155.0.8059.39** through temporary `/tmp` wrapper configs; no browser download or installation was performed. Playwright is 1.63.0. The committed security config uses portable `../.venv/bin/python` and default Chromium, with separate test/output paths; the temporary wrappers only replace the browser channel with `chrome` and resolve local paths.

All following commands ran from `web/` with authorized loopback server access:

| Exact command | Result |
| --- | --- |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-security.config.ts` | **25 passed**, 21.5 seconds. |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-default.config.ts` | **6 passed**, 12.3 seconds; desktop/mobile assessments, claim/login/logout, model edits/tests/removal, profile/filter revisions and import confirmation/replacement/stale drafts. |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-setup.config.ts` | **1 passed**, 10.2 seconds after W10; import/model deferral and correction paths, skipped integrations, failed source recovery and useful jobs. |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-email.config.ts` | **1 passed**, 6.8 seconds; encrypted save, synthetic test worker, disable and narrow layout. |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-sheets.config.ts` | **1 passed**, 7.1 seconds; saved connection/tab selection, preview, queue execution, formula-safe CSV and explicit inward review. |
| `rtk proxy npx playwright test --config /tmp/pipeline-web-security-generation.config.ts` | **1 passed**, 4.8 seconds; preview, automatic draft, persistent disable and manual action. |

Generated `web/test-results-web-security/` is ignored, including its synthetic setup keys and session state. No private profile, actual résumé, credential file, external model/SMTP/Sheets call, container/image/disk operation, commit, push or deployment was used. This evidence covers native Python/SQLite and one browser engine with synthetic external transports; it does not certify live providers, container recovery, other engines, screen readers or the final release. The independent R5 reviewer owns closure and the parent owns the aggregate test/source identity.
