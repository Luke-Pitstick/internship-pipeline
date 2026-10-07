# Internship Pipeline task breakdown

Drafted October 6, 2026 from the [product plan](../OPEN_SOURCE_PLAN.md), [repository audit](open-source-step-1.md), and [feature wishlist](../FEATURE_WISHLIST.md). This is a local execution plan, not published tracker issues or new Codex chats. See the [completion audit](completion-audit.md) for evidence and remaining requirements. T01 and T02 completed their bounded experiments; T02 did not validate automatic rejection. T04 and T05 delivered their implementation slices; T05 live-provider acceptance remains open as explicitly assigned below. T03's implementation is present, but actual container acceptance remains blocked. T06, T10, and T11 have completed implementation handoffs; T06 records 535 integrated Python tests plus browser checks. T07 and T09 have completed implementation handoffs. T12 remains partial pending removal of obsolete pipeline references, now assigned to the T13 worker before downstream work. T08, T13, T14, T15 and T17 are assigned to GPT-6.1 Sol high workers as described below. Other tasks remain pending. T03 actual container acceptance remains blocked on the Docker engine.

Each task should produce a demonstrable behavior or a bounded experiment with recorded results. Work any task whose blockers are complete; numbering gives a suggested order, not an additional dependency. Keep the existing SQLite store, queue, supervisor, collectors, source identity rules, and useful résumé safeguards. Remove superseded implementations when their replacement works; do not introduce compatibility layers or a second task queue.

## Completion and handoff requirements

- Finish every in-scope acceptance criterion, including the browser/API/worker integration needed to demonstrate the promised behavior. A passing isolated module test does not complete an integrated feature.
- Report status as complete, partial, or blocked, with evidence for each criterion. Missing implementation or required verification remains open on the original task; do not turn it into an unnamed follow-up.
- For work intentionally outside the task, name its receiving task ID and add a concrete acceptance criterion there before handoff. Later ownership does not mean the feature already works.
- Record external blockers precisely, including the attempted check and what is needed to retry. Mocked provider tests, native process tests, and synthetic performance tests must not be described as live provider, container, or production performance acceptance.
- Preserve the approved separate Settings page and explicit Applied workflow. Assessments, generated documents, delivered alerts, and submitted applications are separate states.
- Parent review checks these requirements before accepting the handoff. Completed handoff documents are historical evidence; current status belongs here and in the completion audit.

## Milestones

| Milestone | Tasks | User-visible result |
| --- | --- | --- |
| A. First complete search workflow | T01–T07 | Deploy, claim the instance, configure a profile/models, search a real source, and inspect Jev decisions without notifications. |
| B. Daily dashboard and résumé workflow | T08–T13 | Manage searches, sort and track jobs, import a résumé, and generate grounded drafts manually or automatically. |
| C. Optional integrations and setup completion | T14–T16 | Configure email/Sheets and complete a guided setup with either integration skipped. |
| D. Reliable installation and operation | T17–T20 | Back up and restore, run published portable images, install with one command, and manage the installation. |
| E. Open-source release | T21 | Ship a documented, tested release with explicit supported environments and limitations. |

### T01 — Validate the Svelte dashboard interactions

**Blocked by:** None.

**Delivers:** a runnable, synthetic prototype of the jobs list/detail panel, grouped settings form, and progress display that validates the frontend choice before production UI work.

- [x] Exercise server-like pagination over 10,000 synthetic jobs, sorting, detail selection, form validation, and progress updates.
- [x] Verify keyboard operation, focus, a narrow mobile viewport, and distinct posting/first-observed dates.
- [x] Record compressed initial JavaScript and interaction measurements on named hardware; compare against the plan's provisional 200 KB initial-JavaScript budget.
- [x] Record the Svelte/static-deployment decision and any adjustment justified by the measurements. Carry validated UI patterns forward; leave no competing prototype runtime in the product.

### T02 — Validate Jev eligibility and scoring on labeled examples

**Blocked by:** None. Live measurements require a configured Jev credential; fixture and harness work can proceed without it.

**Delivers:** a reproducible evaluation and a versioned rubric for hard constraints and fit dimensions.

- [x] Build a synthetic labeled dataset covering the existing role/eligibility regressions, missing facts, required versus preferred skills, conflicting requirements, and hostile posting instructions.
- [ ] Keep tuning examples separate from held-out evaluation examples; preserve per-criterion labels and expected review cases. **Historical limitation:** six model inputs overlapped; only 28 were unseen. The parent fixed future-run enforcement with a tested overlap guard, but that cannot repair the original experiment. T21 owns new untouched evaluation evidence before automatic rejection can be enabled.
- [x] Measure false rejection of eligible jobs, rejection precision, review rate, ranking usefulness, latency, and usage; record resolved model identity.
- [x] Establish evidence-based thresholds and a release gate. If quality is insufficient, keep affected criteria in review rather than claiming automatic rejection is validated.
- [x] Keep score, eligibility, and model uncertainty separate, with exact arithmetic and date comparisons in code.

### T03 — Boot one container and create the owner account

**Status:** implementation present; container acceptance blocked by the local Docker engine. Native process and browser checks passed. The parent owns reopening this check; T18's wider portability checks do not replace it.

**Blocked by:** T01 — Validate the Svelte dashboard interactions.

**Delivers:** a fresh container serves the application, lets its operator claim it, and supports login/logout before model credentials or a profile exist.

- [x] Package the Svelte shell and FastAPI application behind one port and persistent data volume, reusing the existing process supervisor.
- [x] Require a one-time operator setup token; atomically allow one initial owner and disable claim afterward.
- [x] Implement hashed passwords, authenticated server-side sessions, CSRF protection, login throttling, logout, and an operator account-recovery command.
- [x] Replace the shared bearer-token/Sites-proxy application access path and manual activation-file setup; keep useful job/PDF validation and applied-state behavior behind the new API.
- [x] Distinguish healthy setup mode, liveness, and readiness. Workers needing unconfigured capabilities remain inactive without crashing the setup UI.
- [x] Verify account/data persistence and denied unauthenticated access to private APIs and documents.
- [ ] Build and run the actual image on one working Docker host with a fresh temporary volume; verify claim/login, private-route denial, readiness, volume ownership, restart persistence, and graceful stop. Preserve existing installations. This remains T03 work until demonstrated.

### T04 — Edit and save the candidate profile and search preferences

**Blocked by:** T03 — Boot one container and create the owner account.

**Delivers:** the owner can maintain structured facts, skills, education, availability, eligibility, and search preferences through the settings UI.

- [x] Add the settings category sidebar and focused content panel, with an explicit Save action, validation errors, and saved/unsaved feedback.
- [x] Separate confirmed facts, unknown fields, mandatory constraints, and soft preferences; preserve stable fact identifiers.
- [x] Store immutable profile/settings revisions in SQLite and display which revision is active.
- [x] Workers consume revisions at task boundaries; edits become visible without manually restarting the container.
- [x] Replace personal YAML as the application's profile/settings authority, preserving explicitly backed-up user inputs rather than silently deleting them.

### T05 — Configure and test Jev and the general LLM

**Blocked by:** T03 — Boot one container and create the owner account.

**Delivers:** independent model connections can be configured, tested, edited, and removed in AI Models settings.

- [x] Support Jev's decision API and an explicitly documented general-LLM provider contract, including model selection and custom endpoints where supported.
- [x] Test actual required capabilities with synthetic inputs; show useful authentication, timeout, rate-limit, and unsupported-output errors.
- [x] Store encrypted credentials server-side with a recoverable instance key; redact secrets from API reads, logs, and errors.
- [x] Persist connection revisions, effective model identity, request limits, and usage records needed for the run budget.
- [x] Keep inference behind a narrow client interface and display what candidate information each configured provider receives.

### T06 — Persist and display authoritative Jev decisions

**Blocked by:** T02 — Validate Jev eligibility and scoring; T04 — Edit and save the candidate profile and search preferences; T05 — Configure and test Jev and the general LLM.

**Delivers:** an owner can evaluate a stored job and inspect its eligibility, fit breakdown, uncertainty, and supporting evidence; every consumer reads that same result.

- [x] Replace regex-based semantic rejection and optional chat matching with typed Jev criterion decisions and dimensional scores.
- [x] Persist satisfied/violated/not-stated/ambiguous outcomes, fit, recommendation, evidence references, and model/rubric/profile/job revisions.
- [x] Route uncertain or incomplete assessments to review; a fit score cannot override a mandatory violation.
- [x] Replace dashboard request-time keyword screening with reads of persisted assessments. No inference runs during a jobs GET request.
- [x] Reevaluate affected jobs after relevant changes and suppress stale in-flight results; retries remain inspectable and bounded.
- [x] Render explanations from valid criterion/evidence data, with a clear distinction between fit score and hiring probability.
- [x] Keep model-derived rejection in review while T02's quality gate is unmet. Use exact comparisons only on supported validated normalized facts; T02 did not validate salary extraction/arithmetic or general production extraction accuracy.
- [x] Close T05's live Jev capability-check gap using one synthetic probe through the actual configured client and isolated temporary storage, within the existing credential authorization. Record failures honestly; do not start another paid evaluation sweep.

### T07 — Run a real search without notification prerequisites

**Status:** Implementation handoff complete; see t07-search-workflow.md. Fresh-container and combined live-provider Milestone A acceptance remain unverified.

**Blocked by:** T06 — Persist and display authoritative Jev decisions.

**Delivers:** from the browser, configure a supported company board, run collection and matching, and review jobs with email and Sheets unset.

- [ ] Expose one existing supported source end to end, with validated configuration and a manual Run action.
- [ ] Store opportunities and assessments independently of delivery; remove the mandatory destination prerequisite from worker startup.
- [ ] Expose run state, collected/evaluated counts, source errors, and pending/review/rejected results.
- [ ] Preserve deduplication, first-snapshot backlog labeling, separate timestamps, and incomplete-inventory safeguards.
- [ ] Resume work safely after interruption without duplicate opportunities. Automatic résumé work remains off until explicitly enabled.

**Milestone A acceptance:** a fresh installation completes deploy → claim → model/profile setup → real search → Jev review entirely through the browser.

### T08 — Manage saved searches, schedules, and run progress

**Status:** Implementation handoff complete; evidence in t08-saved-searches.md.

**Blocked by:** T07 — Run a real search without notification prerequisites.

**Delivers:** users can manage multiple saved searches and supported sources, schedule or pause them, and inspect run history.

- [ ] Expose company boards and the existing broad-search connector with source-specific required fields and supported options.
- [ ] Support Run now, pause/resume, explicit backlog review, schedule/timezone, and per-run limits without duplicate overlapping runs.
- [ ] Show current stage, progress, last success, next run, model usage, and actionable source/provider errors.
- [ ] Reconnect the browser's progress feed to persisted state; closing the browser does not stop work.
- [ ] Enforce configured cost/work limits and preserve collector independence from slow inference or delivery.
- [ ] Extend T05's connection-probe limits into persisted run-level budgets and cancellation controls. Probe rate limits alone do not cap production matching or generation costs.

### T09 — Sort, review, and track jobs in the dashboard

**Status:** Implementation complete; see t09-jobs-workspace.md for API/browser/performance evidence.

**Blocked by:** T06 — Persist and display authoritative Jev decisions.

**Delivers:** a fast, paginated jobs workspace with list/detail navigation and useful saved views.

- [ ] Sort ascending/descending by posting date, first observed, company, title, location, deadline, and Jev fit; put unknown values last with stable tie-breaking.
- [ ] Preserve sorting/filtering/selection in the URL and show Recommendations, Needs review, Saved, Applied, and Rejected views.
- [ ] Show original posting, evidence, gaps, decision revision, and original apply link; keep rejected jobs accessible.
- [ ] Allow notes, save/dismiss, explicit mark-applied, and recorded decision overrides without overwriting the model assessment.
- [ ] Keep application state distinct from discovery, evaluation, alerts, and documents; verify keyboard and mobile use.
- [ ] Replace the temporary bounded inventory view with authoritative server pagination/sorting and persisted saved views; carry forward T01's approved interactions. Measure the real API/database path with 10,000 synthetic stored jobs and concurrent progress updates, distinguishing it from T01's simulated transport timings.

### T10 — Import PDF/DOCX résumés into a reviewed profile

**Blocked by:** T04 — Edit and save the candidate profile and search preferences; T05 — Configure and test Jev and the general LLM.

**Delivers:** upload or replace a résumé, review extracted facts alongside source text, and save a confirmed profile revision.

- [x] Handle PDF and DOCX with bounded processing and clear unsupported/encrypted/image-only document feedback.
- [x] Use existing PDF tooling and a maintained DOCX parser; send extraction assistance to the configured LLM only when needed.
- [x] Require review of important inferred fields, retain provenance, and avoid silently converting absent facts into claims.
- [x] Support replacing an upload without losing manually confirmed additions; preview changes before saving.
- [x] Make saved revisions invalidate affected matching work through the shared revision mechanism.

### T11 — Render a master résumé from confirmed profile facts

**Blocked by:** T04 — Edit and save the candidate profile and search preferences.

**Delivers:** a user without LaTeX source can generate, preview, and download a master PDF using an application-owned template.

- [x] Render structured candidate content into one supported template using the existing bounded compiler and PDF validation.
- [x] Preserve factual provenance, contact details, protected values, readable text, page limits, and overflow checks.
- [x] Escape user text and compile application-owned source; uploading a résumé must not grant arbitrary code execution.
- [x] Save the exact profile/template revisions and reuse unchanged output. Display failures with a useful recovery action.
- [x] Preserve the current generation behavior until T12 replaces it; the new master-PDF capability is complete on its own.

### T12 — Generate a job-specific résumé with the configured LLM

**Status:** Partial integration: replacement generator is tested, but obsolete pipeline imports/wiring must be removed by /root/t13_generation_policy_high before T13/T17 proceed. Live OpenAI and Docker verification remain blocked.

**Blocked by:** T05 — Configure and test Jev and the general LLM; T06 — Persist and display authoritative Jev decisions; T11 — Render a master résumé from confirmed profile facts.

**Delivers:** select a job, request a tailored résumé, inspect its changes and warnings, and download the resulting PDF.

- [ ] Generate structured document content from confirmed profile facts and job context through the configured general LLM.
- [ ] Reuse grounding/provenance and PDF checks, separating them from obsolete exact-character-count and personal-template restrictions.
- [ ] Run generation asynchronously, with progress, bounded retries, checkpoints, revision-aware reuse, and stale-result suppression.
- [ ] Work without any notification destination; preserve uncertainty and require user review before treating a draft as ready to apply.
- [ ] Replace and remove the Codex subscription-only generator and its Node/Codex image runtime dependency, obsolete errors, and documentation.
- [ ] Validate the configured general-LLM client through generation and malformed-output/failure handling. Perform a bounded synthetic live acceptance check when an owner supplies a supported provider credential; report a missing credential as a verification blocker, never as a passed live check. T05 initially supports official OpenAI Responses only, not arbitrary compatible endpoints.

### T13 — Control automatic résumé generation separately from filtering

**Status:** Policy implementation handoff complete; integration_cleanup_high owns residual legacy-delivery removal and combined regression verification.

**Blocked by:** T07 — Run a real search without notification prerequisites; T12 — Generate a job-specific résumé with the configured LLM.

**Delivers:** Resume Generation settings control whether and for which jobs the system creates drafts automatically.

- [ ] Provide an off-by-default toggle and explicit qualifying fit, recommendation, and eligibility rules.
- [ ] Show a preview/count of current jobs that qualify and clearly separate generation rules from search inclusion and alert rules.
- [ ] Enforce settings both when enqueueing and claiming tasks; disabling automation prevents pending work from starting.
- [ ] Keep manual generation available and prevent repeated scans or policy saves from creating duplicate artifacts.

### T14 — Configure email alerts and digests

**Status:** Implementation handoff complete; live SMTP acceptance remains blocked pending credentials and authorized send.

**Blocked by:** T05 — Configure and test Jev and the general LLM (secret storage); T07 — Run a real search without notification prerequisites.

**Delivers:** users can connect an email destination, send a test, and receive either qualifying-job alerts or scheduled digests.

- [ ] Reuse Apprise, with user-friendly provider fields, validation, thresholds, schedule/timezone, and explicit enable/disable controls.
- [ ] Queue delivery independently; transport failures never rerun collection, matching, or résumé generation.
- [ ] Persist delivery status, retries, and digest membership; handle uncertain acknowledgements without claiming exactly-once remote delivery.
- [ ] Deliver available PDFs only when requested and supported; job alerts work before any résumé exists.

### T15 — Connect a spreadsheet and sync job records safely

**Status:** Implementation handoff complete; live Sheets acceptance remains blocked pending credentials and authorized remote test.

**Blocked by:** T05 — Configure and test Jev and the general LLM (secret storage); T07 — Run a real search without notification prerequisites.

**Delivers:** users can connect Google Sheets, preview column mapping, and maintain a useful spreadsheet of discovered opportunities.

- [ ] Support one documented self-hosted authorization flow, test access, and choose the destination spreadsheet/tab in the UI.
- [ ] Upsert by stable job ID; map job facts, scores, dates, and links explicitly, with a dry-run preview.
- [ ] Preserve formulas, unrelated columns, and manual notes. Treat candidate/source text as data rather than executable formulas.
- [ ] Persist checkpoints and retry safely after partial failure; surface revoked credentials and conflicts without blocking the pipeline.
- [ ] Define ownership clearly: application facts/scores sync outward; only explicitly mapped status/notes may sync inward, with conflict review. Include CSV export for users without Google.
- [ ] Remove the product's reliance on an SSH download script and local Codex relay for this workflow.

### T16 — Complete guided setup and settings navigation

**Status:** In progress — /root/t16_guided_setup_high; GPT-6.1 Sol high. Complete resumable browser setup and explicit skip/correction paths; actual live/container acceptance must be labeled separately.

**Blocked by:** T07 — Run a real search without notification prerequisites; T10 — Import PDF/DOCX résumés into a reviewed profile; T14 — Configure email alerts and digests; T15 — Connect a spreadsheet and sync job records safely.

**Delivers:** a coherent first-run wizard that resumes across visits and ends on the first useful search result.

- [ ] Connect the existing account, model, profile, search, and optional-integration screens into a resumable sequence.
- [ ] Allow both integrations to be skipped; distinguish incomplete setup from a failed service.
- [ ] Explain which details affect hard filtering, fit, and generation; show a final configuration preview before the first run.
- [ ] Return users to the appropriate settings category when a connection or field needs correction.
- [ ] Verify the complete journey on a fresh volume with only the browser and user-supplied credentials.

### T17 — Add useful diagnostics and complete backup/restore

**Status:** Native implementation/acceptance complete; actual container interruption/restore remains blocked and assigned to t18_container_release_high.

**Blocked by:** T07 — Run a real search without notification prerequisites; T12 — Generate a job-specific résumé with the configured LLM.

**Delivers:** owners can understand degraded operation, retry recoverable work, and restore their installation with its documents and settings intact.

- [ ] Show source freshness, queued/failed work, worker activity, model errors, and sanitized diagnostic logs.
- [ ] Provide a documented consistent backup of database, uploads, generated documents, configuration, and credential-key recovery material.
- [ ] Include both identity/job databases and the exact T05 credential encryption key; test restoring encrypted connections and T10 upload provenance/T11 artifacts together into a fresh instance. A copied key alone is not a full application backup.
- [ ] Restore into a fresh instance without mismatched WAL files, stale evaluations, duplicated jobs, or blind replay of confirmed deliveries.
- [ ] Exercise worker/container interruption, disk errors, provider timeouts, and graceful shutdown with inspectable recovery states.
- [ ] Include a documented owner recovery procedure without exposing a public recovery bypass.

### T18 — Publish portable, versioned container images

**Status:** Assigned preparation and T03/T17 prerequisite verification — /root/t18_container_release_high; GPT-6.1 Sol high. Full acceptance/publication remains gated by T16, container runtime and verified platform evidence.

**Blocked by:** T12 — Generate a job-specific résumé with the configured LLM; T16 — Complete guided setup and settings navigation; T17 — Add useful diagnostics and complete backup/restore.

**Delivers:** a tagged image can run the complete application on each declared supported architecture and runtime.

- [ ] Build and smoke-test amd64 and arm64 images; retain only verified architecture claims.
- [ ] Confirm the outstanding T03 single-host image acceptance has passed before broad portability/release acceptance; never substitute native Python process tests for an actual container run.
- [ ] Validate one-container operation, persistent storage, permissions, signals, health, and URL/port discovery on Docker and Podman before declaring either supported.
- [ ] Add frontend and image checks to CI; publish versioned image references with provenance/dependency information and no personal configuration.
- [ ] Measure pull/start time, image size, idle/run memory, and rendering resources on named hosts; document minimum requirements from those results.
- [ ] Document database-version compatibility and preservation/recovery behavior; do not promise downgrade compatibility or silently reset data.

### T19 — Install with one hosted command

**Status:** preparation assigned October 7, 2026 — `/root/t19_installer_high`, GPT-6.1 Sol high. Installer preparation with explicit versioned image input; live install/hosting acceptance waits for T18.

**Blocked by:** T18 — Publish portable, versioned container images.

**Delivers:** a hosted installer detects a supported environment, obtains the image, starts the application, and prints its usable URL.

- [ ] Define and test the initial OS/architecture/runtime support matrix; proposed first targets are Linux and macOS, subject to T18 evidence.
- [ ] Prefer a healthy supported runtime already installed; offer a clear choice when several are available.
- [ ] When none is usable, guide installation/startup and resume setup without silently installing privileged software.
- [ ] Obtain a versioned image, create persistent storage and an installation manifest, choose/check the port, and wait for setup readiness.
- [ ] Make reruns recognize the existing installation and preserve its data/configuration; show clear recovery steps on failure.
- [ ] Choose the public installer URL and management-command name before publishing; install that command with a self-contained help/status entrypoint.

### T20 — Manage the installation from a reusable command

**Status:** preparation assigned October 7, 2026 — `/root/t20_management_high`, GPT-6.1 Sol high. Management command preparation after agreeing the T19 manifest contract; live lifecycle acceptance waits for a verified image and installation.

**Blocked by:** T19 — Install with one hosted command; T17 — Add useful diagnostics and complete backup/restore.

**Delivers:** the installed management command can start, stop, inspect, and troubleshoot an existing installation without repeating setup.

- [ ] Provide start, stop, status, logs, and open/show-URL commands using the runtime and installation manifest selected by the installer.
- [ ] Show container readiness and available recent-run/activity/error information through authenticated application diagnostics, keeping credentials out of output.
- [ ] Handle stopped runtimes and missing installations with actionable guidance rather than creating a second instance.
- [ ] Preserve the persistent volume across stop/start, and document backup/restore and explicit image-update procedures.

### T21 — Complete release acceptance and open-source documentation

**Status:** preparation assigned October 7, 2026 — `/root/t21_release_readiness_high`, GPT-6.1 Sol high. Documentation and release-readiness review only; release acceptance remains gated by upstream image/install/runtime/live-provider evidence.

**Blocked by:** T02 — Validate Jev eligibility and scoring; T08 — Manage saved searches, schedules, and run progress; T09 — Sort, review, and track jobs; T13 — Control automatic résumé generation; T18 — Publish portable images; T20 — Manage the installation. Earlier dependencies transitively include profile import, manual generation, both integrations, onboarding, and recovery.

**Delivers:** an unfamiliar user can install and operate the released application from public documentation, with current evidence supporting its claims.

- [ ] Choose and add the project license; review dependency/template/font redistribution and remove personal infrastructure references and obsolete setup instructions.
- [ ] Provide quickstart, architecture/contributor guidance, supported-provider/runtime matrix, privacy/data flow, troubleshooting, and backup/recovery documentation.
- [ ] Run fresh-install acceptance through search, Jev review, manual/automatic résumé generation, email/Sheets opt-in and skip paths, and restart/restore.
- [ ] Recheck Jev regression quality, dashboard performance budgets, accessibility, authorization, secret handling, and integration retry behavior.
- [ ] If automatic rejection is proposed, obtain fresh representative human-adjudicated labels, separate tuning inputs from untouched evaluation inputs, and meet T02's recorded gate (300 eligible examples with zero false rejections, at least 30 rejection examples with at least 98% precision, at least 95% review recall, and at least 20 ranking comparisons with at least 80% agreement). The existing six overlapping model inputs cannot count as unseen validation. Until then, release with model rejections routed to review and explicitly describe that limitation; budget and authorize any new paid evaluation separately.
- [ ] Verify live supported-provider behavior with supplied credentials, real serving/compression, keyboard/screen-reader and narrow-screen behavior, and declared browser support. Publish measured coverage; T01's prototype measurements and T05's mocked transport tests cannot stand in for these checks.
- [ ] Publish measured limits and unresolved issues honestly; remove retired paths and the temporary prototype so there is one supported product workflow.

## Initial execution order

Start with T01 and T02, which have no code dependencies. Proceed through T03–T07 for the first complete product. T09, T10, T11, T14, and T15 can be taken when their listed blockers are satisfied; they do not need to wait for every lower-numbered task. This describes dependency options, not authorization to launch multiple agents or chats.

Tracker publication, effort estimates, and external issue numbers remain unassigned. Current agent ownership and outstanding handoff work are recorded in the completion audit.

## October 7 execution boundary

The native integrated suite passed 525 Python tests, six default browser tests and one dedicated setup journey. Actual image acceptance remains blocked: the Colima engine became responsive, but its build paused with a root-disk nospace error; the test-started runtime is stopped. T19–T21 are authorized for independent preparation only. No image, hosting URL, supported-runtime certification or live release acceptance is implied by simulated installer/management tests. Restoring sufficient disk capacity or supplying a healthy authorized build host remains necessary before the image gate can pass.
