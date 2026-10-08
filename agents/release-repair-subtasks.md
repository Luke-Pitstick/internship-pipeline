# Defect repair and release completion plan

Generated October 7, 2026; updated October 8. Status: **R1–R5 complete for the local native/synthetic repair scope; R6 GitHub Actions candidate prepared and statically reviewed.** All 16 original defects independently pass, with additional revision/navigation/stream-cleanup/package repairs verified. See [combined verification](../docs/repairs/combined-verification.md) for the tested source identity and current evidence. R6–R9 external acceptance remains open; no candidate was pushed or dispatched.

## Outcome and scope

Deliver the promised self-hosted application: obtain one verified container image, create an owner in the browser, configure models and a reviewed profile, search and inspect jobs, generate grounded documents, optionally enable email/Sheets, and operate and recover the installation without editing application code.

This plan covers all **16 confirmed review findings (3 P1, 12 P2, 1 P3)** and every outstanding boundary in [release-readiness.md](../docs/release-readiness.md). It follows [task-breakdown.md](../docs/task-breakdown.md) and closes its incomplete acceptance criteria rather than declaring the T01–T20 implementation handoffs to be release certification.

Source packets:

- [Backend review](../docs/reviews/backend-review.md): B1–B6.
- [Web/security review](../docs/reviews/web-security-review.md): W1–W6.
- [Operations review](../docs/reviews/operations-review.md): numbered findings 1–4, called O1–O4 below.
- [Integrated acceptance](../docs/integrated-acceptance.md), [T18 image evidence](../docs/t18-portable-images.md), [T19 installer](../docs/t19-installer.md), [T20 management](../docs/t20-management.md), and [redistribution review](../docs/redistribution-review.md).

The earlier 525-test native baseline and installer/management 82-pass/1-skip result describe separate snapshots. Neither is the final release result, and passing those tests did not prevent the review reproductions. A new frozen source revision and exact image digest must identify the final evidence.

## Working rules

- Preserve ordinary Python, SQLite, the existing durable queue, established provider contracts, separate Settings, and explicit Applied tracking. Remove obsolete paths; do not add compatibility layers.
- Convert each confirmed finding into a deterministic failing regression before its repair, then retain the test. Capture the triggering behavior, not a test that simply repeats implementation logic.
- Use the original report to understand the reproduction; temporary `/tmp` scripts may no longer exist. Reconstruct synthetic fixtures in the repository's existing tests when needed.
- Reuse existing transaction/lease fencing, revision checks, validation, Svelte state APIs, Python path/URI APIs and maintained dependencies. Check current APIs/types before adding abstractions or packages. No new queue, distributed lock service or general settings framework is required by this plan.
- Each worker owns its stated modules. Shared changes require a handoff, not simultaneous edits. The integration owner maintains the defect ledger and task statuses.
- A task is complete only when all required implementation and acceptance checks pass. Use `partial` or `blocked` for missing evidence. Report preparation, native simulation, real container execution and live-provider behavior separately.
- Planning does not authorize disk deletion, runtime resets, paid calls, external test messages, remote spreadsheet writes, publication, or a project-license choice. These actions require the concrete inputs/authorization listed below; already-authorized local implementation and synthetic tests can proceed independently.

## Defect ledger

Every row must end with a repair reference, regression command/result and reviewer sign-off. All rows are initially open.

| ID | Priority | Repair | Required regression | Owner |
| --- | --- | --- | --- | --- |
| B1 | P1 | Give saved-search targets one collection owner. The ordinary collector must exclude all browser-owned sources, not just Greenhouse. All admitted saved-search work must retain its run/budget identity. | Lever, Ashby and JobSpy stay paused/deleted/outside schedule even when the ordinary collector is active; a newly discovered job cannot bypass zero job/call/token budgets; independent operator sources still work. | R1 |
| B2 | P1 | Atomically checkpoint SMTP outcome, attempt and queue transition under the current lease. Recognize accepted/cancelled/uncertain delivery states before transport. | Inject crashes before/after each checkpoint, expire the lease and restart: accepted delivery is not sent twice; uncertain delivery requires explicit owner retry. Preserve uncertainty when SMTP outcome cannot be known. | R2 |
| B3 | P2 | Revalidate queued email members against current assessment identity, thresholds and owner/job state immediately before transport admission. Rebuild eligible digest content or cancel an empty delivery. | Profile/model/posting changes, dismissal, rejection, closure and marking applied suppress stale queued content; a mixed digest retains only current eligible members and does not attach a current PDF to an obsolete score. | R2 |
| B4 | P2 | Scope lease-expiry/retry transitions to the kinds owned by the claiming worker. | An email worker with a three-attempt ceiling cannot fail a master-resume task with five attempts; the owning worker still enforces its ceiling, including concurrent claims. | R1 |
| B5 | P2 | Export all CSV rows using bounded iteration. Make Sheets capacity limits explicit before a plan is accepted; never silently truncate source inventory. | 10,001+ jobs all appear once in CSV; Sheets either covers the declared inventory or returns a clear capacity error before writes. Boundary sizes, stable ordering, fingerprints and formula protection remain correct. | R4 |
| B6 | P2 | Determine opportunity closure from all relevant direct-source observations, not the one alias missing from the latest scan. | One alias disappears while another direct board still reports the job: no false closure/reopening event. Close only when the supported complete-inventory evidence warrants it; partial scans remain safe. | R1 |
| W1 | P1 | Bind editor drafts to the revision from which they were loaded. Poll operational status separately; never advance the draft's expected revision underneath unsaved fields. | Two real browser contexts: tab B disables/edits an integration; tab A saves its older draft and receives a conflict without overwriting B. Email remains disabled; Sheets mappings stay intact; explicit reload resolves it. | R3 |
| W2 | P2 | Clone the plain Sheets configuration through the supported Svelte snapshot boundary. | Load and reopen a saved connection; fields populate, edit/save/reload works, and no reactive-Proxy `DataCloneError` occurs. | R3 |
| W3 | P2 | Bound anonymous-session issuance with persistent atomic admission controls, expiration cleanup and an active anonymous-session cap. Reuse a valid session rather than allocating another. | Cookie-free bursts and concurrent callers cannot grow SQLite without bound; limits survive restart; untrusted forwarded headers do not bypass them; existing owner sessions and normal claim/login/CSRF flows still work. | R3 |
| W4 | P2 | Track dirty state for every editable Settings category and setup step. Retain ordinary drafts across categories and require explicit discard before losing them; keep secrets out of persistent browser storage and clear them on save/discard. | Models, sources, generation policy, email and Sheets edits survive category navigation or present an effective discard guard. Route/back/refresh and setup transitions cannot silently lose changes. | R3 |
| W5 | P2 | Restore mobile detail visibility along with URL-selected job state, including history navigation and focus behavior. | At 390px, directly open/reload a selected-job URL and use back/forward: visible correct detail, usable Back/Escape, sensible focus, and graceful unknown-job handling. | R3 |
| W6 | P3 | Parse Settings fragments defensively and resolve malformed/unknown categories to a valid route state. | Invalid percent escapes, unknown categories and normal hashes never render a 500; known categories still restore correctly. | R3 |
| O1 | P2 | Encode filesystem paths in SQLite URIs, use read-only source opens where appropriate, and validate expected database identity/schema as well as byte/hash integrity. | Paths containing `?`, `#`, spaces and Unicode preserve both populated databases through backup/verify/restore. An accidentally empty or wrong database fails verification instead of receiving a successful backup certificate. | R4 |
| O2 | P2 | Preserve bounded stdout and stderr for runtime log commands and sanitize both before display. Keep other command-result contracts explicit. | Fake engine emits lifecycle failures on stderr: management logs show the failure while secrets remain absent; success/failure exits and output bounds behave correctly. Later repeat against a real container. | R4 |
| O3 | P2 | Remove obsolete fields from supplied deployment configuration and reconcile active Render/configuration documentation with current workers and settings authority. | Every shipped current settings example passes the actual strict loader. Current startup uses it successfully; removed fields are not accepted via a fallback. | R4 |
| O4 | P2 | Replace running-container recovery instructions with a complete stop → exact-image maintenance command on the preserved volume → restart procedure. Keep the offline lock. | Active writers correctly block recovery; stopped maintenance rotates the token/password, revokes sessions and preserves data; documented commands match Compose/installed endpoints. Actual container procedure is proven in R6. | R4 |

## Execution order and ownership

Use three worker slots initially:

1. **Backend worker:** R1, then R2. It owns collection/storage/queue repairs before changing email checkpoint logic that depends on that queue contract.
2. **Web/security worker:** R3. It owns integration editors and the identity/API admission boundary.
3. **Data/operations worker:** R4. It owns Sheets export backend, backup/runtime tooling, shipped configuration and recovery documentation.

R2 owns `email_integrations.py`; R3 owns its editor, not its backend revision contract. R4 owns `sheets_integration.py` export changes; R3 owns `SheetsSettings.svelte`. R1 publishes any shared queue transaction interface before R2 uses it. R3 owns `app.py` session admission edits; other workers request mounts instead of editing the same sections. No implementation worker marks its own review findings resolved without regression evidence and independent confirmation.

Critical path: **R1–R4 repairs → R5 frozen candidate → R6 actual image/recovery → R7 live integrated checks → R8 candidate distribution → R9 fresh install and release sign-off**.

R6 host-capacity diagnosis and R8 license/registry/URL decisions can happen while repairs run; actual acceptance waits for the repaired candidate. R7 provider credentials/test destinations can also be prepared early. Missing external inputs remain explicit blockers, not reasons to call downstream preparation complete.

## Agent-ready task cards

### R1 — Repair collection ownership, queue expiry and source closure

**Inputs:** B1/B4/B6 in the backend review; T07/T08/T06 handoffs; `collection.py`, `search_runs.py`, `run_limits.py`, `storage.py`, `queue.py` and their tests.

**Own:** these three repairs and their focused regressions. Preserve source, first-observed and notification timestamps independently. Audit all saved-source types, not only the reproduced Lever case. Prefer explicit existing source ownership over expanding provider-name conditionals.

**Done when:** B1/B4/B6 ledger regressions pass and a mixed-worker restart test demonstrates independent retry policies and preserved budget membership. Current deduplication/incomplete-inventory tests still pass. Supply a stable queue checkpoint contract to R2 if an additional transaction hook is needed.

**Depends on:** none. **Handoff:** repair evidence and a short shared-interface note; do not broaden this into scheduler redesign.

### R2 — Make email recovery and member admission correct

**Inputs:** B2/B3, current email task/attempt/member schemas, R1's queue contract and existing uncertainty/retry tests.

**Own:** `email_integrations.py` and email checkpoint/admission tests. Keep SMTP transport external to database transactions, but make local outcomes and task transitions atomic and lease-fenced. An ambiguous external send remains uncertain; do not promise exactly-once SMTP delivery.

**Done when:** B2/B3 regressions pass for single alerts and digests, accepted/uncertain/permanent/transient outcomes, lost leases and explicit retries. The worker does not send stale recommendations or replay an already-recorded accepted/uncertain send. Attachments come from the matching supported revision.

**Depends on:** R1 before changing shared queue transitions. **Handoff:** crash-window evidence, ledger invariants and focused tests. No real email is needed here.

### R3 — Repair browser state and anonymous-session admission

**Inputs:** W1–W6, current Settings/onboarding/editor lifetimes, `identity.py`, session routes, dashboard URL state and existing browser configurations.

**Own:** all six web/security findings. Fix W1 first, then W2/W4 as one coherent editor-state contract; keep polling status separate from editable state. W3 must use current SQLite/auth infrastructure rather than new proxy or distributed services.

**Done when:** every W regression passes, with an actual two-context browser conflict test and native concurrent-session admission tests. Default and dedicated setup browser suites pass, including integration skip/correction paths. Run keyboard/focus and narrow-screen checks for changed flows; extend supported-browser coverage in R5.

**Depends on:** none; coordinate field contracts with R2/R4 without competing backend edits. **Handoff:** per-finding browser/API evidence and explicit chosen session limits with rationale and restart behavior.

### R4 — Repair exports, backups and operational instructions

**Inputs:** B5/O1–O4, `sheets_integration.py`, `operations.py`, installer/runtime/management helpers, shipped YAML and active deployment/Render docs.

**Own:** five repairs, tests and operational-doc corrections. Stream or page complete CSV using current database APIs; keep remote Sheets plans bounded with explicit capacity failure. Use standard-library URI/path construction and SQLite read-only/backup facilities rather than string escaping or a replacement backup framework.

**Done when:** B5/O1–O4 native/synthetic regressions pass, large exports are complete, wrong/empty DB backups are rejected, both output streams retain useful sanitized lifecycle errors, and every shipped configuration validates. Run maintenance CLI under both active and stopped instance locks. Mark actual image recovery commands pending R6 rather than claiming mocked engine tests prove them.

**Depends on:** none. **Handoff:** corrected operational contract and executable same-image recovery steps for R6/R9.

### R5 — Independently review repairs and freeze a release candidate

**Inputs:** R1–R4 patches/regressions, all three review reports, existing native/browser suites and installer/manager tests.

**Own:** integration verification and the defect ledger. Have reviewers independently rerun the triggering scenarios and inspect fixes; no blanket closure based on a green aggregate count. New defects are assigned and retested before freezing.

**Acceptance:** all 16 findings resolved with evidence; full current Python suite including installer/management passes; Ruff, strict mypy, Svelte check/build pass; all required dedicated/default browser suites pass on their correct fixtures. Explain every skip; environment skips for required behavior must be rerun in a capable environment.

Declare the first-release browser/accessibility matrix before testing it. Cover keyboard-only operation, focus/dialog/error handling, a real screen reader, 320/390px layouts, settings conflicts and job deep links. Verify the existing 200 KB initial compressed-JavaScript budget and real 10,000-job API interactions, labeling hardware/network/sample sizes. Do not infer untested browser support from Chromium.

**Done when:** evidence is tied to a frozen source revision, no open confirmed review defect remains, and the candidate's intended support matrix is explicit. Container serving/compression and resource measurements remain R6.

**Depends on:** R1–R4. **Handoff:** reviewed candidate source identity and test/coverage manifest; later code changes invalidate the affected evidence and require a new candidate.

### R6 — Obtain a healthy build host and prove the actual image

**Inputs:** R5 candidate, T18 candidate CI and smoke/recovery runner, R4 maintenance instructions, existing Colima attempt evidence.

**First unblocker:** choose sufficient build-host capacity or an authorized healthy remote/CI host. The prior Colima image build stopped with root-disk `nospace`; no image was produced. Inspect current capacity before retrying, retain partial-runtime evidence and user volumes, and do not reset/prune/delete data as an assumed permission. Stop repeated builds when the same capacity condition persists.

**Own:** real image build and runtime acceptance, narrowly fixing packaging/runner defects. Start with one declared primary platform to obtain a working end-to-end image, then verify each additional advertised architecture/runtime. Proposed targets remain native Linux amd64/arm64 with Docker/rootless Podman; unsupported combinations must be removed from the claim rather than silently counted as passing.

**Acceptance:** built frontend/API on one published port; owner setup/login/logout/private-route denial; correct UID/volume writes; readiness; same-volume restart and setup continuation; graceful signals and forced interruption; complete fresh-volume backup/restore of both DBs, exact key, uploads/provenance and PDFs; no replay of confirmed external work; sessions revoked after restore. Run `deploy/container-smoke.py --recovery` on uniquely owned resources and preserve sanitized reports.

Measure image size, build/start time, idle/run/PDF memory and disk headroom on named hosts. Check actual HTTP serving/compression. Pull-time measurement follows candidate registry availability in R9; never fabricate numerical minimums from native Python tests. Inspect the actual image's SBOM, dependency/TeX/font contents, ownership and build-context exclusions. Verify candidate artifact digest is the image tested by CI.

**Depends on:** host readiness and R5 for authoritative application acceptance. **Handoff:** image digest, source revision, host/runtime matrix, measured requirements, lifecycle/recovery evidence and exact remaining unsupported targets. An image-build-only pass does not complete this card.

### R7 — Verify the supported external contracts and full product journey

**Inputs:** R6 image, owner-supplied test credentials/destinations and explicitly bounded external-test authorization. Use synthetic candidate facts and a disposable installation; never substitute real private resumes as fixtures.

**Own:** a small live acceptance set, not another broad evaluation sweep. Freeze request caps, generation/token limits, timeouts, recipients and sheet destinations before calls. Record actual or unknown usage and stop after a failed bounded attempt rather than retrying indefinitely.

- **Search/Jev:** one approved public-source run through browser setup and the actual saved Jev client; inspect persisted job/evidence/model/profile identities, run budgets and review routing. The historical capability probe is useful prior evidence but does not prove the current image's full journey.
- **General LLM:** one bounded synthetic manual generation through a supported official OpenAI Responses model, verify selected facts/provenance and actual PDF/review/download. Exercise an explicitly enabled automatic policy with a similarly bounded job set, then disable it and confirm manual generation remains available.
- **Email:** with explicit send authorization, deliver to a designated test inbox and verify receipt, digest behavior and a requested PDF attachment. Keep crash/uncertainty failure injection local; do not deliberately duplicate real messages to test recovery.
- **Sheets:** with explicit write authorization, use a disposable shared sheet for access, preview, stable-ID upsert/readback, unrelated formula/manual-cell preservation, reviewed inward notes/status and revoked-access behavior. Bound changes and clean up only the owned test data; retain local synthetic partial-failure tests.
- **Complete browser journey:** fresh owner → models → reviewed profile/import → source/filter preview → first useful jobs → mark/undo applied → manual/opt-in automatic document → integration opt-in and independent skip paths → restart/restore. Provider errors must lead to the correct settings screen without losing drafts.

**Policy for first release:** keep model-derived rejections in review. Automatic rejection remains a separately gated extension requiring fresh representative human-adjudicated examples, untouched tuning/evaluation separation, at least 300 eligible examples with zero false rejection, at least 30 rejections at 98% precision, 95% review recall and 20 ranking comparisons at 80% agreement. If automatic rejection is required for this release, that gate becomes blocking; it cannot be replaced by raising a confidence threshold.

Also confirm that the released tailoring contract is grounded selection/reordering of confirmed wording. Broader rewriting is not silently promised by the current implementation; a changed requirement needs its own implementation and factuality acceptance.

**Depends on:** R6 and test inputs/authorization. **Handoff:** sanitized provider/journey evidence with image digest, usage, external effects and observed limits. Missing credentials mean blocked acceptance, not missing implementation magically resolved by mocks.

### R8 — Finalize license, distribution and release documentation

**Inputs:** owner decisions, redistribution inventory, R5/R6/R7 evidence, T18 workflow, T19 artifact/manifest and T20 CLI.

**Own:** release identity and packaging. Early work may inventory notices and draft documentation while fixes run. Obtain the owner's project-license choice and verify authority for source/design assets; add the selected root license/package metadata and required dependency/template/font notices. Inspect actual image contents rather than treating declared package metadata as legal clearance. Set a private security-reporting contact and supported-version policy.

Choose the registry/repository, immutable version/digest conventions, installer artifact URL, command name and checksum/signature verification policy. Build a versioned, self-contained installer/management bundle with the agreed manifest; pin verified images and reject unverified mutable/default substitutions. Publish a release **candidate** only after its technical gates and publication authorization, with provenance/SBOM/checksums and exact source linkage. Do not label the installer generally available before R9 exercises that hosted artifact.

Update README, contribution, privacy/data-flow, troubleshooting, supported-provider/runtime/browser matrix, measured resource requirements, owner recovery, backup/restore and explicit update/downgrade limitations. Remove obsolete active instructions and personal infrastructure references; keep historical audit documents labeled historical. License and support claims must match evidence.

**Depends on:** owner decisions can proceed now; candidate distribution waits for R5–R7. **Handoff:** exact candidate image and hosted artifact references, integrity metadata, notices, documentation and publication record. No invented URL or untested platform claim.

### R9 — Prove hosted installation and approve the release

**Inputs:** R8 hosted candidate/image, capable hosts from the declared matrix, an operator who did not implement the installer, and existing T19/T20 acceptance scripts.

**Own:** final real installation and release decision. From the exact documented hosted command, test fresh install, runtime choice/missing-runtime guidance, port conflict, readiness/URL/token retrieval, browser claim, idempotent rerun with the same data, copied/custom-path management bundle, start/stop/status/sanitized logs/authenticated diagnostics and owner recovery. Exercise backups/restores using the same image, missing-resource safety and an explicit image-update path preserving data. No silent second instance or replacement volume.

Measure published-image pull/start behavior and update resource guidance. Test every advertised host/runtime combination or narrow support explicitly. Have the new operator complete first search and restore from only the published documentation; correct every missing step and rerun affected acceptance. Treat actual runtime behavior as distinct from fake-executable unit tests.

**Final release gate:** all 16 defects independently closed; R5–R9 required checks pass; no unresolved blocking failure; license/notices/security contact/support policy present; source revision and artifact digests traceable; documentation matches actual behavior; credentials/private fixtures absent from distribution. Promote the exact accepted candidate artifacts without rebuilding different bytes. If any code/artifact changes, repeat affected gates before promotion.

**Depends on:** R8; can prepare scripts/checklists earlier. **Handoff:** final acceptance matrix and public release references, or precise blocked status. The integration owner updates T01–T21 status from evidence, not from whether an agent finished its turn.

## External inputs and decisions

| Input | Needed by | Work that can proceed without it |
| --- | --- | --- |
| Healthy authorized build host with sufficient disk capacity, or permission for a concrete non-destructive host remedy | R6 | All defect repairs, native/browser checks and distribution drafting |
| Official general-LLM test credential/model; bounded Jev/search test budget | R7 | All provider-contract mocks, compiler/PDF checks and image lifecycle tests |
| Test SMTP credential/recipient and explicit send authorization | R7 | Email replay/stale-membership repairs and synthetic transport checks |
| Dedicated Sheets service account/disposable shared sheet and explicit write authorization | R7 | Complete-export, formula/conflict and mocked-provider tests |
| Owner-selected license, security contact, registry/installer hosting and publication choice | R8 | Notice inventory, documentation drafts and local candidate artifacts |
| Release scope decision if fully automatic Jev rejection or freer résumé rewriting is required | R7/R8 | Existing review-only decisions and grounded selection/reordering remain the proposed release contract |

## Suggested next dispatch

Launch the three repair lanes **R1→R2**, **R3**, and **R4** with exact file ownership and test obligations above. Do not launch more release-preparation agents to work around the same uncorrected defects. The parent/integration owner can arrange the build-host and license/test-input decisions while those workers repair code, then dispatch independent R5 verification against the combined candidate.

The release is ready only after the final gate passes. An unfinished external check stays visibly blocked even when its code and test harness are implemented.
