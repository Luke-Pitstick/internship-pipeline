# T16 — Resumable guided setup

October 6, 2026. **Partial: implementation and fresh native/synthetic acceptance pass; the actual fresh-container journey with owner-supplied live credentials remains open.** The initial native handoff had an unavailable Docker engine, and no authorized general-model, SMTP or Google Sheets credential was supplied. Current image/runtime evidence belongs to [T18](t18-portable-images.md); the native tests below do not establish live provider acceptance or actual container operation.

## Flow and durable state

The owner claim/sign-in boundary leads unfinished installations to `/setup/`. The sequence is models, profile/résumé review, job filters, optional integrations and final configuration preview. `onboarding_state` stores the current step, reviewed steps, model deferral, separate email/Sheets choices and completion. Closing the browser or restarting the application preserves progress. The main navbar appears only after completion; setup is never a navbar item. Settings correction links remain available inside setup. Completed owners visiting `/setup/` return to Jobs.

`SettingsWorkspace.svelte` is the shared implementation of both the separate Settings page and the guided steps. It reuses the existing model, reviewed résumé import, profile, filter, source, SMTP and Sheets components and their APIs. There is no second owner account, profile, credential store, connection probe or queue. A profile with explicitly reviewed unknown fields can be saved and used for collection. The owner can defer models, which leaves fit/evaluation or tailored generation pending; résumé import continues to extract locally without inference.

Email and Sheets independently accept Connect or Skip, covering all four combinations. Connect requires current verified readiness, while Skip removes that setup prerequisite and leaves a failed service visibly failed. Skipping an already enabled integration does not silently disable its saved configuration; the preview shows the chosen setup path and actual saved enablement separately. Incomplete means missing/unverified settings. Failed means an application-owned recorded model probe, SMTP operation or Sheets operation failed. Sheets access-test results now persist only revision and a sanitized success/failed/invalid status in the integration's own `sheets_tests` table; a failed access probe revokes tested readiness, and a new configuration revision does not inherit the old failure. Invalid/missing fields remain incomplete and require correction.

The setup explanations distinguish hard eligibility constraints and confirmed authorization/availability/education, soft preferences and rubric fit, and fact-grounded draft generation. Fit measures rubric alignment, not interview probability. Full source inventory is stored independently of model review budgets. Initial backlog review remains explicit. Automatic generation is off by default, and the final preview shows its actual current rules and enablement. Discovery, assessment, drafts, delivered alerts, owner-reviewed spreadsheet changes and Applied remain separate; finishing setup never submits or marks an application.

## Preview and correction contract

GET `/api/onboarding` reads authoritative current profile, model, generation, email and Sheets state and derives broad searches from saved preferences. Each role/country/location combination becomes an internship query; required locations take precedence over preferred locations. Supported countries use Indeed; unrestricted or unsupported countries use LinkedIn location searches without assuming US eligibility. Empty roles produce a general internship query. Terms, skills and candidate eligibility remain matching inputs. More than 100 combinations or oversized query fields require correcting preferences. The final preview includes profile and connection revisions, confirmed-fact count, hard/soft preferences, selected models/readiness, generated searches, model-work limits, generation rules and integration choices/enablement. It contains no model key, SMTP password, service-account material or private path. It is owner authenticated and uses the existing no-store response boundary.

POST `/checkpoint` persists review choices, and POST `/visit` saves the current step. POST `/finish` requires the displayed preview fingerprint and all setup prerequisites. One SQLite transaction saves the generated searches, queues their collection and marks setup complete. A replay cannot create duplicate searches or runs. The browser immediately opens Jobs while collection continues independently. The application supervisor checks the durable completion state every two seconds and starts collection workers automatically, without restarting the application. Email/Sheets workers remain available during setup for connection tests, and profile-dependent résumé workers follow their own readiness gates. Native previews use `python -m internship_pipeline.bootstrap --reload` so API reloads retain worker supervision. Empty results, source failures and deferred models do not reopen setup. Existing manually configured sources are preserved. The obsolete start/first-results setup flow is removed. All mutations retain owner, session, CSRF and origin protection.

Correction links open `/settings/?setup=1#<category>`. Settings includes a return link to the saved setup step and the main navbar remains hidden. Returning to the preview recomputes searches from the latest saved preferences; stale previews cannot finish setup.

## October 11 onboarding simplification

The Saved search and First results setup steps are removed. “Finish setup and find jobs” completes setup before collection returns. Local verification uses synthetic candidates and provider responses; live collection and container deployment remain separate acceptance gates. Historical acceptance below describes the earlier flow. The current flow passes 90 focused Python tests, the complete fresh-installation browser journey, 9 main browser cases and 24 navigation/security cases. Svelte check reports zero errors/warnings; the production build, scoped Ruff, strict mypy and whitespace checks pass. A 390px setup preview was visually inspected with no horizontal overflow. The saved-search browser suite adds 2 passing cases. A broader run completed with 976 Python passes and one failure in concurrent résumé-import work: the old `test_document_rejections[anything-tex-Only PDF]` expectation conflicts with newly supported `.tex` validation. That unrelated work was preserved.


## Automatic worker activation

October 11: collection workers activate after durable onboarding completion; the supervisor
checks readiness every two seconds. The development `--reload` launcher uses the same supervisor.
The native subprocess regression claims an owner, confirms collection is inactive, completes
onboarding over HTTP, observes a queued search become collected through a real CLI worker with
synthetic provider I/O, then restarts the app and verifies persisted jobs and worker recovery.
Both normal and reload modes pass. The combined bootstrap, supervisor, onboarding, owner and
assessment suite passes 101 tests; scoped Ruff, strict mypy and whitespace checks pass. The current
local preview also reached 39 collected jobs after replacing the web-only process with the
supervised launcher; this is local runtime evidence, not container acceptance.

## Per-criterion evidence

| T16 criterion | Status and evidence |
| --- | --- |
| Connect account/model/profile/search/integration screens in a resumable sequence | Implemented and verified natively. The fresh browser claims the owner, saves/tests model connections, imports/reviews synthetic DOCX facts, reloads the saved profile, reviews filters and saves a search; SQLite/API tests restart the application and coordinator with the saved step intact. |
| Allow both integrations to be skipped and distinguish incomplete from service failure | Implemented. Nine focused setup tests include all four independent Connect/Skip combinations, verified SMTP acceptance through a synthetic transport, real Google authentication/HTTP adapter with synthetic responses, unconfigured connections, failed model/SMTP access and a durable revoked-Sheets access test. The browser encounters failed email, corrects the setup choice and finishes with both integrations skipped. |
| Explain hard filtering/fit/generation and show final preview before first run | Implemented and verified. The browser confirms the complete saved preview before the first source run; stale-preview backend tests change a profile revision and assert no run is admitted. Replays reuse the stored run, and generation remains off. |
| Return corrections to the proper Settings category | Implemented and verified. The browser follows integration/model/source links, checks category headings, corrects rejected model credentials and a failed source, returns to its saved step and runs the corrected revision. |
| Complete fresh-volume journey with browser and supplied credentials | **Blocked for the supported container/live boundary.** One fresh temporary native installation passes the full Chromium/API/SQLite/worker journey using synthetic credentials and provider transports only. Actual Docker volume/image operation and live credentials were unavailable. T16 retains this open criterion; native evidence does not complete it. |

## Verification and reproduction

- Nine focused T16 tests plus the eleven existing Sheets integration tests pass (**20 passed**). They use actual SQLite, owner/session APIs, ATS parsing and queue workers; provider I/O is synthetic transport. Four independent integration choices never write a remote sheet or send real email. The earlier combined setup/identity/profile/model/search/Sheets/email regression passed **82 tests** before the additional Sheets-status case; its new status boundary is covered by the final 20-test run.
- The dedicated real Chromium journey passes in **7.7 seconds** (10.5 seconds including fixture startup). It begins with a fresh temporary native installation, claims the account, reviews imported synthetic source facts, resumes after reload, observes a rejected model credential and failed SMTP test, chooses both integration skips, corrects/tests both models through their real HTTP probe adapter, confirms the preview, observes failed source collection, edits the source in Settings, returns/reviews/runs, finishes on the first stored job and reloads the completed workspace. ATS transport responses pass through the real installed scraper and normalizer; collection/evaluation/email use native independent workers. There is no browser interception of the product API. A 390px screenshot was inspected and the test asserts no horizontal overflow.
- Final combined acceptance now passes **525 Python tests in 44.73 seconds**, with one existing Starlette TestClient deprecation warning. Full source/tests Ruff and true `mypy --strict` pass all **55 source modules**; Svelte check reports **zero errors and warnings**, the production static build passes, and `git diff --check` passes. [Integrated acceptance](integrated-acceptance.md) records the repaired recovery-fixture mock leak and isolated temporary-directory reproduction.
- The default Chromium suite passes **6 tests in 12.7 seconds**, including its desktop/mobile assessment cases with explicit completed-onboarding and current saved-search-run responses. Its configuration excludes `setup.spec.ts`, and CI runs the dedicated setup configuration separately. A fresh dedicated setup rerun passes **1 test in 9.2 seconds** (7.5 seconds in the test). The earlier automatic approval-review deadlines were resolved by approved local-loopback runs; no assertions were weakened or approval boundary bypassed.

Run from the repository root:

```sh
rtk proxy env PYTHONPATH=src .venv/bin/pytest tests/test_onboarding.py tests/test_sheets_integration.py -q
rtk proxy .venv/bin/ruff check src/internship_pipeline/onboarding.py src/internship_pipeline/onboarding_router.py src/internship_pipeline/sheets_integration.py tests/test_onboarding.py
rtk proxy .venv/bin/mypy src/internship_pipeline/onboarding.py src/internship_pipeline/onboarding_router.py src/internship_pipeline/sheets_integration.py
```

From `web/`, run `rtk npm run check`, `rtk npm run build`, then `rtk proxy npx playwright test --config playwright.setup.config.ts`. Its fixture binds loopback port 4184 and uses isolated ignored `test-results-setup/` output, preventing other Playwright suites from deleting its synthetic setup token. The default Playwright configuration excludes this dedicated test. Existing Settings regression uses `rtk proxy npx playwright test --config playwright.config.ts`.

T18 consumes the ready setup route/API and native evidence for image/CI checks; its image runner can preserve a deferred-model checkpoint across restart and fresh restore. Retrying the still-open T16 boundary requires a responsive Docker engine, the supported image on a new persistent volume, browser-only owner claim and configuration with owner-supplied authorized credentials, connection correction/reload and independent integration skips, then a first observed useful job. Live tests require bounded explicit authorization for any inference, external email or remote spreadsheet write. No `.env`, actual résumé, private candidate input, live credential, paid model request, external email, remote sheet mutation, commit, push or deployment was used here. No T19/T20 installer work is included.

## October 11, 2026 — Purpose-built onboarding inputs

Onboarding and Settings now share `svelte-multiselect` controls, with country names and aliases from `i18n-iso-countries`. Required countries offer name/code search, flags and removable selections. Locations, terms, skills and authorization descriptions use explicit tags added with Enter; commas remain part of a single entry, so “Denver, CO” survives saving and reloading. Skills offer suggestions without treating preferences as confirmed evidence. Native date, email, number and short select controls retain their platform behavior.

Saved searches use searchable timezones, named job-site choices, and country choices supplied by the installed JobSpy country enum. The backend validates country support before saving. Composite controls explicitly disable during saves. The existing résumé autofill work is preserved: PDF/DOCX extraction fills the ordinary editable profile, then Save changes confirms the review. File selection now validates format/size immediately, describes the selectable-text requirement, displays the selected filename/size and processing stages, and explains non-JSON proxy upload failures with a retry path.

Verification: 68 focused Python tests passed (46 résumé-import/onboarding and 22 search-run tests). Nine targeted Chromium cases passed: five profile/upload cases, two saved-search cases, the complete fresh-installation setup journey, and the setup country-field unsaved-change guard. The setup journey includes keyboard country selection, reviewed résumé saving/reload, failed connection correction, independent integration skips and a first observed job. Tests use temporary native installations, synthetic credentials/documents and synthetic provider transports. They do not establish actual-container or live-provider acceptance. Svelte check passed with zero errors/warnings; production build, focused Ruff and mypy checks passed. Impeccable's detector reported no findings. Desktop and 390px mobile captures were inspected; overflow assertions passed.

Reproduce from `web/` with `rtk npm run check`, `rtk npm run build`, then:

```sh
rtk proxy npx playwright test profile.spec.ts resume-import.spec.ts --config playwright.config.ts
rtk proxy npx playwright test --config playwright.search.config.ts
rtk proxy npx playwright test --config playwright.setup.config.ts
rtk proxy npx playwright test --config playwright.web-security.config.ts -g 'W4 setup 3'
```

Run suites sharing `test-results/` sequentially. Screenshots are generated in ignored `web/test-results/`, including `onboarding-countries-desktop.png`, `t04-filters-mobile.png` and `t10-resume-import-mobile.png`. No production deployment was performed.
