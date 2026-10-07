# Web and HTTP boundary review

Reviewed October 7, 2026 at HEAD `e9f4c012ef3c14f709abe7a20ab416fdebff13c2`, including the current worktree. This is a read-only review of the frontend and HTTP boundary for T01–T20. The only repository change made by this reviewer is this report. Temporary, entirely synthetic reproduction scripts are in `/tmp/pipeline-web-review.cjs` and `/tmp/pipeline-http-review.py`.

**Verdict:** Changes are needed before treating the browser configuration workflow as complete. Six findings are listed below: one P1, four P2, and one P3. No owner-authentication bypass, executable posting HTML, credential disclosure, or unsafe PDF path was found in the reviewed paths. Those negatives describe the coverage below, not a claim that all vulnerabilities are excluded.

## Confirmed findings

### W1 — P1: Polling advances the integration save revision without updating its draft

**Locations:** [EmailSettings.svelte:12](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/EmailSettings.svelte:12>) and [EmailSettings.svelte:16](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/EmailSettings.svelte:16>); [SheetsSettings.svelte:16](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SheetsSettings.svelte:16>) and [SheetsSettings.svelte:23](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SheetsSettings.svelte:23>). The backend revision comparisons are at [email_integrations.py:147](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/email_integrations.py:147>) and [sheets_integration.py:163](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/sheets_integration.py:163>).

**Trigger and mechanism:** Open Notifications & Integrations with configuration revision 1 and keep a draft based on it. Save revision 2 from another browser tab, for example disabling automatic delivery or sync and changing the recipient, destination, or mapping. After the three-second poll, the first tab stores revision 2 in `data` but retains its older `draft`. Save sends that stale configuration with `expected_revision: 2`, so the server's otherwise correct optimistic-conflict check accepts it.

**Impact:** The first tab can silently reverse a deliberate disable decision and overwrite newer recipients or spreadsheet mappings. Email can resume delivery using the overwritten configuration. Sheets saves clear tested readiness, so its later sync still depends on the access-test gate, but the owner's saved disable/destination decision has already been overwritten. This warrants P1 because the lost update changes controls for subsequent external delivery and writes, not merely a display preference.

**Evidence and confidence:** Confirmed in Chromium against the existing static application, with every API response intercepted using synthetic data. After another simulated tab changed `enabled` from true to false and advanced revision 1→2, the browser submitted email `{expected_revision: 2, enabled: true, recipient: "draft@example.test"}` and Sheets `{expected_revision: 2, enabled: true, tab: "Draft Jobs"}`. For Sheets, fields were entered manually because W2 prevents loading the saved draft. Source inspection confirms both services compare the supplied revision to the current revision; this test did not send mail or write a spreadsheet. Confidence: high.

**Fix direction:** Keep the draft's base revision tied to the snapshot from which that draft was initialized. Poll delivery/sync activity separately, and require an explicit reload or conflict resolution when configuration changes. Only an accepted save or deliberate reload should advance the draft's base revision.

### W2 — P2: Saved Google Sheets settings cannot populate the editor

**Location:** [SheetsSettings.svelte:14](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SheetsSettings.svelte:14>).

**Trigger and mechanism:** Save a Sheets connection, then reload Settings, return to the integration category, or use Reload Sheets settings. `load()` assigns the API result to reactive `$state` variable `data`, then calls `structuredClone(data.config)`. That property is now a Svelte reactive Proxy, which `structuredClone` rejects.

**Impact:** A returning owner sees blank initial spreadsheet settings and default mappings instead of the saved connection, while the application continues to hold its real configuration. The owner cannot reliably inspect or edit the existing destination and mappings, and manually rebuilding the form risks overwriting them.

**Evidence and confidence:** Chromium reproduced an empty Spreadsheet ID and the displayed message `Failed to execute 'structuredClone' on 'Window': #<Object> could not be cloned.` for a non-null saved connection. This is independent of live Google access. Confidence: high.

**Fix direction:** Clone the plain API result before assigning it to reactive state, or clone `$state.snapshot(data.config)`. The same repository already uses the snapshot approach in `SourceSettings.edit()` for this exact class of error.

### W3 — P2: Anonymous session issuance has no admission limit

**Locations:** [app.py:219](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/app.py:219>)–222 and [identity.py:159](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/identity.py:159>)–167. Login/claim throttling is separately applied at [app.py:229](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/app.py:229>)–237.

**Trigger and mechanism:** Repeatedly request `/api/session` without retaining a valid session cookie. Each public GET inserts a new server-side anonymous session. These requests never reserve an authentication attempt, and there is no per-peer issuance limit or maximum anonymous-session population. Cleanup deletes expired sessions but does not limit how many can accumulate during the 20-minute lifetime.

**Impact:** An unauthenticated caller can force sustained SQLite writes and unbounded anonymous-session growth within each lifetime window. On a public deployment this exposes the identity store and shared persistent volume to avoidable availability pressure. Actual disk exhaustion or outage was not attempted; that consequence is an inference from the confirmed admission gap.

**Evidence and confidence:** An isolated FastAPI TestClient and temporary database received 100 cookie-free session requests, producing 100 live `owner_sessions` rows and zero `owner_attempts` rows, without throttling. No existing installation was used. Confidence: high for the gap; workload and storage thresholds for an outage remain unmeasured.

**Fix direction:** Bound and throttle anonymous session issuance before allocating a row, and enforce an overall anonymous-session admission limit while retaining expiry cleanup. Verify that login/claim can still obtain a challenge under normal use and that attacker requests cannot keep allocating storage indefinitely.

### W4 — P2: Non-profile settings drafts disappear on category changes without warning

**Locations:** [SettingsWorkspace.svelte:30](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SettingsWorkspace.svelte:30>)–40, [SettingsWorkspace.svelte:73](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SettingsWorkspace.svelte:73>), and [SettingsWorkspace.svelte:108](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SettingsWorkspace.svelte:108>)–111; [AiModelSettings.svelte:10](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/AiModelSettings.svelte:10>)–28. Guided setup consumes this incomplete dirty state at [setup/+page.svelte:27](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/routes/setup/+page.svelte:27>)–30 and 51–52.

**Trigger and mechanism:** Edit a model or connection without saving, switch to another Settings category, then return. The parent tracks only its profile/filter snapshot and pending résumé import. Conditional rendering destroys the other components and their local drafts; neither category navigation nor the route guard knows those drafts are dirty. The same dirty callback drives the setup Continue button.

**Impact:** Unsaved models, source settings, generation rules, and integrations can be discarded silently. Guided setup can report that changes are saved or permit continuing even though a displayed connection draft was never saved. This violates the intended explicit-save and unsaved-feedback workflow and increases the likelihood of running an older configuration.

**Evidence and confidence:** Chromium changed the saved General LLM model from `saved-general` to `unsaved-general`, switched AI Models → Profile → AI Models, and observed `saved-general` again with no confirmation dialog. The additional category scopes and guided setup consequence are confirmed by the parent/component lifetimes and dirty-state wiring; only the model category round trip was exercised dynamically. Confidence: high.

**Fix direction:** Preserve each category's draft across category changes, or register its unsaved state with the shared navigation/setup guard and require deliberate discard. Derive Continue availability and its feedback from every active settings editor, not only the profile/filter snapshot.

### W5 — P2: A job deep link restores selection but hides its detail on mobile

**Locations:** [routes/+page.svelte:20](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/routes/+page.svelte:20>), [routes/+page.svelte:89](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/routes/+page.svelte:89>)–105, and [app.css:816](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/app.css:816>)–826. The in-page selection handler opens the detail separately at [routes/+page.svelte:48](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/routes/+page.svelte:48>)–52.

**Trigger and mechanism:** Open or reload `/?selected=<job-id>` at the supported 390-pixel mobile viewport. The API response restores `selected`, but `detailOpen` stays false. Mobile CSS hides `.job-detail` unless `.detail-open` is present; only clicking a card sets that state.

**Impact:** The selected job's details are absent from the visible and accessible page after following a direct link. If it is outside the current page or filter, the owner has no corresponding card to click. The T09 direct-selection/reload requirement is incomplete on mobile despite desktop selection restoration.

**Evidence and confidence:** Chromium at 390×844 loaded `/?selected=synthetic-job`, retained that selected URL parameter, and attached the selected heading to the DOM while `isVisible()` returned false. Pressing Enter on its card opened and focused the detail, demonstrating that the failure is specific to restoring URL state. Confidence: high.

**Fix direction:** Open the detail when an explicit selected job is restored from the URL, including navigation restoration. Keep automatic first-row selection distinct from a direct-link selection so ordinary mobile list loads can still start in the list.

### W6 — P3: An invalid encoded Settings hash crashes the route

**Location:** [SettingsWorkspace.svelte:34](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/web/src/lib/components/SettingsWorkspace.svelte:34>).

**Trigger and mechanism:** Navigate to `/settings/#%E0%A4%A`, or another malformed percent-encoded category hash. The reactive effect calls `decodeURIComponent` without handling its `URIError`.

**Impact:** SvelteKit replaces Settings with `500 Internal Error`; a malformed bookmark or link prevents using that route until its hash is corrected. This is a recoverability issue, not an authentication bypass or XSS finding.

**Evidence and confidence:** Chromium reproduced the rendered 500 page. The framework handled the exception internally, so the test's `pageerror` event list was empty; DOM text supplied the failure evidence. Confidence: high.

**Fix direction:** Treat malformed or unknown hashes as an unrecognized category and retain a safe default. Decode inside a guarded parser rather than throwing from the render effect.

## Verification performed

- `rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_owner_app.py tests/test_profile_settings.py tests/test_resume_import.py tests/test_onboarding.py`: **67 passed** in 8.50 seconds. This covers singleton claim, session rotation/revocation/expiry, login throttling and recovery, owner/CSRF denial, validation redaction, immutable profile revisions, bounded import processing/provenance, setup choices and stale-preview rejection. An initial invocation without `PYTHONPATH=src` failed collection; the corrected invocation above is the passing evidence.
- `rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_model_connections.py tests/test_dashboard_api.py tests/test_job_workspace.py tests/test_master_resume.py tests/test_tailored_resume.py -k 'auth or csrf or invalid or unsafe or bounds or symlink or pdf or malicious or validation or denied or unknown or traversal'`: **30 passed, 62 deselected** in 3.11 seconds. This adds narrow credential/endpoint/error, hostile posting, document delivery, and validation coverage. Both runs emitted the existing Starlette/httpx TestClient deprecation warning.
- `/tmp/pipeline-http-review.py` flattened the current FastAPI included routers and sent requests to **61 private method/path combinations**, including known router operations and the unknown-API fallback. All returned **401** without an owner session. The same temporary application proved W3. It used a fresh temporary database and synthetic setup token, not real credentials.
- `/tmp/pipeline-web-review.cjs` served the existing ignored static build on an ephemeral loopback port and intercepted **all** API traffic using synthetic values. It demonstrated W1, W2, W4, W5, and W6. Those affected source branches match the observed build behavior; no build or dependency install was performed during this read-only review.
- The synthetic Chromium case also verified Enter selection focuses the mobile detail heading, Escape restores focus to the original job button, and the inspected 390×844 jobs viewport has no horizontal overflow. This is bounded keyboard/mobile evidence, not a screen-reader or comprehensive accessibility audit.

## Coverage and positive observations

Reviewed the full frontend route/component/API-helper source under `web/src/`: all three pages, layout/state setup, styles, shared types and settings validation, and ProfileSettings, JobFilterSettings, ListField, SettingsWorkspace, AiModelSettings, ResumeImport, MasterResume, TailoredResume, SourceSettings, SearchRun, GenerationPolicySettings, EmailSettings, SheetsSettings, and Diagnostics. Inspected the corresponding browser tests and task handoffs to compare promised behavior with actual paths.

Reviewed `app.py`, `identity.py`, `bootstrap.py`, profile persistence and its router, onboarding coordinator/router, résumé import/extraction, dashboard serialization and workspace query/mutation boundary, model/email/Sheets/generation/search/diagnostics router registration and error mapping, and master/tailored PDF reads. Inspected dependency declarations and the installed python-docx XML parser's `resolve_entities=False` configuration; no registry vulnerability audit was run. Codebase-memory's project inventory contained no index for this repository, so discovery used targeted `rg` and bounded source reads; no indexing or export was attempted.

The private routers consistently inherit the owner dependency. Mutations require the session CSRF token, reject foreign Origin and cross-site Fetch Metadata, and are bounded before body parsing. Claim is serialized and consumes its one-time setup row; recovery revokes sessions. HTTPS enables Secure HttpOnly `__Host-` cookies, and private API responses are not cached. Validation errors omit submitted values, including passwords. Model tests use fixed official endpoints and application-authored failures rather than echoing raw provider responses.

Posting text is reduced to plain text and rendered using escaped Svelte expressions. Application URLs receive HTTP(S)/userinfo validation before serialization. Job sorting uses a fixed expression allowlist and values are parameterized; application submission remains an explicit independent mutation. Résumé uploads use magic/format checks, page/expansion/text limits, a serialized extraction subprocess, and timeout/CPU limits. Linux extraction also applies an address-space limit. Download paths validate generated identifiers/filenames and use no-follow, regular-file, size, magic, and digest checks. These are the actual reviewed controls, not assurances derived merely from suite counts.

## Spec gaps, subjective observations, and external limits

W4 and W5 are demonstrated specification/workflow gaps; W1, W2, W3, and W6 are demonstrated implementation or resource-management defects. None of the findings is based on a subjective preference for a different framework, queue, database, or module organization. The existing ordinary Python/SQLite services and separated Settings route fit the requested architecture; no compatibility layer is proposed.

Backend worker internals, queue leases, model budgets, inference quality, generation factuality, and email/Sheets execution are assigned to the backend reviewer. In particular, queued SMTP content becoming stale after profile changes is that reviewer's finding and is not duplicated here. Backup/restore, installers, managed commands, image packaging, and actual deployment/runtime behavior are assigned to the operations reviewer.

Docker/image/volume lifecycle, live model behavior, real SMTP acceptance, actual Google writes, provider retention, production reverse-proxy/HTTPS behavior, and deployed response compression were not exercised. Existing handoffs disclose container/runtime and some live-provider acceptance gaps; they remain verification limits, not newly discovered code bugs or passing release evidence. No `.env`, private candidate profile, real résumé, live credential, sensitive history search, external message, commit, deployment, container runtime, or image operation was used. Browser evidence is Chromium only; screen-reader operation, other engines, and low-end hardware remain unreviewed.

**Security-review skill result:** FAIL for the P1 configuration safety issue, with the additional P2 anonymous-session admission gap. Authentication, authorization, CSRF, SQL/input handling, XSS/URL rendering, uploads/downloads, secret/error redaction, and dependency/boundary coverage were examined within the limits above. No source repairs were made.
