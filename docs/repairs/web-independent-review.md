# Independent web/security repair review — R5

October 8, 2026. **PASS W1–W8 and the two additional review findings W9/W10 on the settled local snapshot. No unresolved confirmed finding in this review scope.** This reviewer did not author the production fixes. The only repository source/document write is this report; additional reproducers/configs are under `/tmp`, and browser fixtures produce ignored test outputs.

Read the original web/security review, R3/R5 requirements, dispatch controls, current source/test diff and relevant API consumers. Production source, retained tests and frontend build were not modified by this reviewer. Browser execution was coordinated with the author after their final build and release of port 4187. All application state, owner inputs, destinations and provider replies were synthetic. No actual candidate profile, user credentials, paid provider request, external SMTP message, remote Sheets write, runtime/image lifecycle, disk cleanup, commit or deployment was used.

## Finding decisions and observed mechanisms

| Finding | Independent decision and evidence |
| --- | --- |
| W1 — stale email/Sheets draft revisions | **PASS.** `EmailSettings.svelte:12` and `SheetsSettings.svelte:16` pin revisions to the draft's loaded/accepted-save snapshot. Three-second status polling updates activity without rebasing the draft. Independent real two-browser-context cases save a newer disable/recipient or mapping in B, wait for A's actual poll, and verify A's stale save returns **409** while B's stored values remain intact. Explicit reload then populates B's configuration. Current backend revision checks remain enabled. |
| W2 — reactive Sheets clone | **PASS.** `SheetsSettings.svelte:21` clones `$state.snapshot(data.config)`, avoiding the reactive Proxy clone failure. Independent browser execution saves a connection, reloads/reopens it with ID/tab populated, changes the inward mapping, saves and reloads it successfully. No Google request leaves the synthetic adapter. |
| W3 — bounded anonymous admission | **PASS.** `Identity.anonymous_session()` (`identity.py:159`) serializes cleanup, peer/global checks, counters and insertion with `BEGIN IMMEDIATE`. The HTTP route (`app.py:219`) uses it only when no valid cookie exists and returns **429** with `Retry-After: 300` on denial. Limits are 20 new guests per peer/300 seconds, 100 globally/300 seconds and 128 active anonymous sessions; hashed peer keys avoid storing raw addresses. Existing sessions and authenticated login/claim remain usable when new-guest admission is full. Independent original-source reconstruction shows the original unbounded HTTP behavior; current native, extra concurrency/rollback tests and the real browser-fixture HTTP burst pass. Spoofed forwarded headers do not create different client identities. |
| W4 — draft/navigation/setup guards | **PASS.** `SettingsWorkspace.svelte:30–35` preserves visited child editors while categories change and aggregates their dirty callbacks with profile/filter/import state. Route and unload guards consume all dirty state (`:80`, `:87`). Child editors retain drafts in memory and supply deliberate discard/reload actions; secret fields clear on save/discard and remain absent from browser storage. Setup guards its keyed editor and explicit setup choices. Independently passed ordinary-category round trips, rejected route navigation, six guided-editor cases, model/integration choices, selected-file-before-extraction, secret clearing/storage checks and the extra failed-transition cases below. |
| W5 — mobile deep links/history/focus | **PASS.** `+page.svelte:34` derives `detailOpen` from `selected`; refresh retrieves the selection and focuses its heading. Select/close push history entries while refresh preserves the existing framework history state. Independent 390×844 browser case opens a bookmarked job detail, returns to results and removes `selected`, selects using Enter, goes back/forward, closes with Escape and restores row focus without horizontal overflow. |
| W6 — malformed category hash | **PASS.** `SettingsWorkspace.svelte:39` catches decode failure and chooses Profile for malformed/unknown categories. The independent browser run navigates to `#%E0%A4%A` and `#unknown` and finds usable Settings/Profile fields rather than the original rendered 500. |
| W7 — generation preview rebases a stale draft | **PASS.** `GenerationPolicySettings.svelte:11` pins `draftRevision`; preview may update counts/view but only a loaded snapshot or accepted save advances the draft base (`:18`, `:27`). Independent two-context test saves B's disable/minimum-fit change, previews A's old rules, then verifies A's save returns **409** and B's policy remains unchanged. The generation-policy service still compares `expected_revision` inside its transaction (`generation_policy.py:104`). |
| W8 — model-test completion rebases an older editor | **PASS.** `AiModelSettings.svelte:15` keeps per-provider draft revisions. A capability-test response updates status but does not change the editor's base; save/remove use that base (`:37`), and explicit reload loads current fields/revisions. Independent two-context test holds a synthetic Jev probe until B saves another model, completes A's test, and verifies A's stale save returns **409** with B's model preserved. The real model API deliberately returns a current summary after completing the old attempt; the editor now handles that contract. |
| W9 — Email Reload during save | **PASS after review repair.** This reviewer identified the source race: Reload was outside the disabled fieldset, allowing a held save's draft to be replaced before its completion advanced the revision. The author reproduced the enabled-control failure and disabled Reload while busy (`EmailSettings.svelte:42`). Independent held-request regression verifies Reload is disabled and the submitted/current recipient remains the intended value. |
| W10 — rejected setup step change clears retained dirty state | **PASS after review repair.** This reviewer identified `visit()` clearing dirty state before the server accepted the transition. The author reproduced a rejected visit retaining the editor while enabling Continue. `setup/+page.svelte:25–31` now returns action success and clears dirty only after a successful transition. Independently passed the retained source-editor regression and a separate reviewer-written profile-editor variant: accepting discard followed by injected **409** keeps the unsaved name, disables Continue and preserves the unload guard. |

The review returned W9/W10 to the author before sign-off. No source fix was made by the reviewer; both repairs were inspected and tested after the author settled them. Session issuance now has bounded state and admission work, but this is not a claim to prevent every availability attack or to measure an outage threshold.

## Independently reconstructed original W3 failures

`/tmp/web-independent-original-setup-20261008.py` copied current `src/` to `/tmp/web-independent-original-20261008/src`, then replaced only `app.py` and `identity.py` with exact bytes from HEAD `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`. Unrelated backend repairs remain present; this is a targeted original-boundary reconstruction, not a full historical release execution.

```sh
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python /tmp/web-independent-original-setup-20261008.py
rtk proxy env PYTHONPATH=/tmp/web-independent-original-20261008/src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_owner_app.py::test_cookie_free_session_burst_is_bounded_and_survives_restart tests/test_owner_app.py::test_concurrent_cookie_free_http_admission_is_atomic --basetemp=/tmp/web-independent-w3-red-20261008 --tb=short
```

**Two intended defect assertions failed in 2.24s.** Original HTTP behavior admitted all 35 sequential cookie-free requests and all 32 concurrent callers, instead of the first 20 plus 429 denials. Setup/import completed normally.

The original W1/W2/W4/W5/W6 browser behavior is documented in `docs/reviews/web-security-review.md` and matches the original source branches inspected here. [The author's final evidence](web-security.md) records the original browser reds, including W7/W8 save acceptance **200** instead of **409**, W9 enabled Reload during a held save and W10 enabled Continue after a rejected transition. **This reviewer did not rerun a pre-fix frontend build**, so those historical browser-red claims remain attributed to their original observers. Independent final green execution below exercises their real triggers and validates persisted consequences, beyond checking source or test counts alone.

## Current native and additional adversarial verification

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_owner_app.py tests/test_profile_settings.py tests/test_resume_import.py tests/test_onboarding.py tests/test_model_connections.py tests/test_generation_policy.py --basetemp=/tmp/web-independent-native-20261008-v1 --tb=short
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q /tmp/test_web_independent_identity_20261008.py --basetemp=/tmp/web-independent-adversarial-identity-20261008 --tb=short
```

**112 passed in 16.64s** and **two reviewer-written adversarial tests passed in 0.21s**. These cover atomic admission across two independent `Identity` instances, rollback of counters/session insertion when a trigger aborts allocation, expiration cleanup even when admission is denied, exact window-boundary admission, restart persistence, per-peer/global/active-session limits, valid guest/owner reuse, login/claim/recovery, owner/CSRF checks and adjacent saved profile/import/setup/model/generation behavior. The 112 run emitted the existing Starlette TestClient deprecation warning; no tests skipped.

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/app.py src/internship_pipeline/identity.py tests/test_owner_app.py
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m mypy --strict src/internship_pipeline/app.py src/internship_pipeline/identity.py
rtk proxy git diff --check -- web/src src/internship_pipeline/app.py src/internship_pipeline/identity.py tests/test_owner_app.py web/tests/web-security.spec.ts
```

Ruff passed, strict mypy reported no issues in two source files, and the scoped diff whitespace check passed.

## Independent browser execution

From `web/`:

```sh
rtk proxy npx playwright test --config=/tmp/web-independent-security-20261008.config.ts
rtk proxy npx playwright test --config=/tmp/web-independent-adversarial-20261008.config.ts
```

**25 dedicated cases passed in 21.5s**, followed by **one reviewer-written profile-draft failure-injection case passed in 3.3s**. Both `/tmp` configs import the committed dedicated configuration, use the installed `channel: 'chrome'`, keep the same dedicated synthetic fixture, and use distinct `/tmp` Playwright output directories. The first invocation could not bind loopback port 4187 under the shell sandbox; the same command was then approved for local test-process/server access and passed. No browser download or dependency install occurred. Installed Chrome version **155.0.8059.39** was independently read from app metadata.

The dedicated fixture starts a fresh real owner API and static frontend with a temporary database, runs actual HTTP/SQLite revision checks, mocks model HTTP responses and Google OAuth/Sheets responses only inside that fixture process, and uses no email transport worker. W1/W7/W8 use separate browser contexts and actual persisted backend state. The W10 extra case intercepts only the intended visit request with a synthetic 409; the rest of that profile/setup flow remains real. Browser warnings were the existing Starlette deprecation and NO_COLOR/FORCE_COLOR notices. `lsof -nP -iTCP:4187 -sTCP:LISTEN` returned no listener after these runs.

This independent review did not rebuild the frontend, run unrelated browser suites or start any installation runtime. The author's final report records Svelte check with zero errors/warnings, a passing build and 35 browser cases across the dedicated/default/setup/email/Sheets/generation suites; these remain **author-observed** evidence. The independent 25 dedicated cases overlap those 35 and must not be added to them. Desktop checks used 1440×1000 and the mobile case used 390×844. This is installed Chrome/Chromium-family evidence only; Firefox/WebKit, 320px layouts, real screen-reader testing, the complete accessibility/support matrix, 10,000-job performance and deployed compression remain broader R5/R6 gates.

## Reviewed source identity

The reviewed sources remain uncommitted against HEAD `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`, alongside the backend and operations lanes. Source SHA-256 values captured during the settled independent browser run:

| File | SHA-256 |
| --- | --- |
| `src/internship_pipeline/app.py` | `d96d66f69c5cd0340339b08275328a21c2f9603623716d8e37780c5ec1ce535d` |
| `src/internship_pipeline/identity.py` | `7e47b93f32325c8c4d5a65358185a66fe49d888d5e2bc29272f0db36c0ee03e2` |
| `web/src/lib/components/AiModelSettings.svelte` | `83425c8ccf5f1827d722a657673cfdeeabc57e4b35b964683dbd772882991cc9` |
| `web/src/lib/components/EmailSettings.svelte` | `9bc5593da066e2066b989726e31e8adc9e4a426cc4fda5046e328fb0d600c4a9` |
| `web/src/lib/components/SheetsSettings.svelte` | `f6486906730fe108098f118c3f3e0599e7659e0779ce37c97fee527d35941f90` |
| `web/src/lib/components/GenerationPolicySettings.svelte` | `863733de12ba72e5b80583ce7f33b21abb22fdeb35cc9810c435207af9d69b13` |
| `web/src/lib/components/SettingsWorkspace.svelte` | `a4963dc708a389b649076fbdad1b144cc2bd4077bf4ef14104035d720b6c13e1` |
| `web/src/lib/components/SourceSettings.svelte` | `86bd5212934f1e99a221c22108a6ce7c61411c7d001d702d9c4ef56396790435` |
| `web/src/lib/components/ResumeImport.svelte` | `985e31374ee8927aed8e378327c734820af35a571f04f8f15ffdea0fa5fb1797` |
| `web/src/routes/+page.svelte` | `0f69ebd8215deba445e350973063f0a77121e68c25f744ffccdccc2878b9b88d` |
| `web/src/routes/setup/+page.svelte` | `d766f55d3b4bcbb898e86afc9dd9a9ad8dcda9781888bde19edf6c93601eb517` |
| `web/tests/web-security.spec.ts` | `2741c2cf08e8a1c1890d2ca213240db264e20abab8d52ae308837e2fb66016d6` |
| `web/tests/web-security-serve.py` | `b87d9a2c209ed7c8544684f88ac19e659c8c6fcfedbcf78e9124ec0bf93b64a2` |
| `web/playwright.web-security.config.ts` | `0a9740b296f9860b55b2a0e2636bfe73cbfbbce582f818c74deee9f93eb17b61` |

All listed source/test hashes were unchanged on the final recheck. The integration owner can record independent closure for W1–W10 on these bytes. Later edits require affected re-verification; this report does not freeze a release candidate or mark external deployment/provider/distribution gates passed.
