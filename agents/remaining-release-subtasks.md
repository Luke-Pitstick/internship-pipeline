# Remaining release tasks after candidate CI

Generated: October 8, 2026. This is an execution brief, not acceptance evidence.

## Goal and ownership

Finish the release gates downstream of the reviewed candidate's GitHub Actions run. The active chat **Plan Internship Pipeline overhaul** owns committing/pushing that candidate, dispatching the workflow, and fixing its failures. This brief does not duplicate that work or assume it passes. Source HEAD was moving during inspection; bind all future evidence to the final successful commit and artifact identities returned by that chat.

Keep the first-release contract: one container, SQLite, TypeSafe SystemOne, optional SMTP and Sheets, grounded selection/reordering of confirmed resume wording, and model-derived rejections routed to review. The concurrent provider task committed OpenAI, Claude and OpenRouter support as `8f14e54`; bind live acceptance to that final provider contract and keep each provider's live evidence separate. No cross-release database compatibility or migration layer is part of this work.

Source of truth: `docs/release-readiness.md`, `agents/release-repair-subtasks.md` R6–R9, `docs/task-breakdown.md`, and the current implementation. The older implementation plan's Step 12 trial still needs an explicit disposition; historical Resume Matcher/Dot acceptance does not apply to the current product.

## Handoff required from the CI owner

Before downstream image acceptance, obtain:

- Exact source SHA, successful Actions run URL, and the source/browser gate results.
- Native amd64 and arm64 Docker and rootless Podman smoke/recovery reports, with failed or untested combinations labeled.
- Downloadable OCI candidate artifacts, their checksums/config identities, SBOM/provenance and the recorded comparison to the tested image.
- Remaining limitations and any changes made after the previously recorded 692-test native candidate.

CI covers much of the image lifecycle work already. Consume its actual evidence; repeat only absent checks or checks invalidated by changes. A registry manifest digest will be recorded after publication; do not confuse it with a local image/config ID.

## Concrete inputs and decisions

Credential availability has not been inspected for this brief. Reuse existing authorized test credentials when available; otherwise the owner supplies them through private application settings or a private ignored input path. Never put secrets in this plan, reports, screenshots, command arguments or Git.

| Input | Exact fields or decision | Needed for |
| --- | --- | --- |
| Jev test connection | TypeSafe API key and accepted model ID; official endpoint is fixed by the app; approved source board/search and synthetic profile | Current-image capability and matching journey |
| General model | API credential and exact model for each advertised OpenAI/Claude/OpenRouter path, required structured-output capability, timeout/output-token settings | Actual tailoring; a Jev credential or subscription login cannot substitute |
| External-test envelope | Permitted model attempts including probes/retries, local reservation budget, provider/account spending limit if available, time window and stop rule | Bounded paid acceptance |
| SMTP | Host, port, `starttls` or `ssl`, username/password, sender, one recipient inbox, ability to inspect receipt, and authorization for the specified messages | Receipt, digest and PDF verification |
| Sheets | Dedicated service-account JSON key, spreadsheet ID, tab, selected columns, Editor sharing, permission to write/read back and temporarily revoke this test account's access | Real sync and recovery |
| Project identity | License choice, copyright holder/year, confirmation of source/template/asset authority, contribution terms and private security contact | License/notices/package metadata and security policy |
| Distribution | Registry/repository, installer artifact host, initial version, final command name, public/private access decision and integrity-verification policy | Candidate image and installer publication |
| Support scope | Exact OS/architecture/runtime and browser versions to claim; hosts/tester available for each; screen-reader environment | Honest support matrix and installation acceptance |
| Trial | Disposition of implementation-plan Step 12; if retained, always-on host, approved source set, duration, notification destination and separate run budget | Scheduling/cadence/latency acceptance |

Proposed operational defaults for owner review: retain `internship-pipeline` as the command; place versioned images and installer assets alongside the existing GitHub project if its release-access policy allows it; pin images by digest; start acceptance with one Linux Docker target before expanding. These are proposals, not selected publication settings. Do not promise macOS support from Linux CI results.

## Execution shape

- **Now:** S1 test preparation, S3 QA/trial planning, and S4 license/artifact preparation can proceed without an accepted image. S5 can prepare hosts and the installation checklist.
- **After CI:** S2 runs the live journey; S3 measures the serving image; S4 inspects its actual SBOM and packages accepted artifacts.
- **Critical path:** CI image handoff → S2/S3 technical acceptance → S4 candidate publication → S5 exact hosted installation → S6 release sign-off.
- S1 is required before S2. Decisions/input preparation can run concurrently; each task has a distinct editing area. No task here has been dispatched.

## S1 — Prepare a bounded live acceptance run

**Outcome:** An executable run sheet with private input references, synthetic profile/posting facts, explicit call/send/write caps and evidence fields.

**Own:** New acceptance preparation and evidence templates under `docs/release/`; any small optional runner under `deploy/` must exercise the real saved-client/application path. Do not change provider contracts or bypass authentication, queue admission or review policies.

**Context:** `docs/t05-model-configuration.md`, `docs/t12-tailored-resumes.md`, `docs/t13-generation-policy.md`, `docs/t14-email-alerts.md`, `docs/t15-spreadsheet-sync.md`; `providers/connections.py`, `assessments.py`, `run_limits.py`, `email_integrations.py`, `sheets_integration.py`, and their existing browser fixtures.

**Instructions:**

1. Create an isolated installation identity and synthetic candidate with enough supported facts for a readable resume. Select a bounded public ATS board/source and capture its identity. Avoid consuming private resumes or reusing a personal Sheet.
2. Preflight saved connection/destination readiness without printing secrets. Record exact model IDs and revisions, SMTP security mode, test destination aliases, source identity and Sheet mappings.
3. Propose this small successful path: one capability probe per model; up to two job assessments; one manual and one explicitly opted-in automatic generation; three delivered emails (settings test, individual alert with PDF, digest with separate eligible membership); and a two-job Sheet upsert/repeat/inward-review/revoked-access sequence. The owner approves the actual attempt/spending/send/write envelope before execution.
4. Account for real retries and for probes outside the search-run ledger. Search runs expose `max_jobs`, `max_calls` and `max_tokens`; the default values are too broad to assume acceptable for this trial. Automatic and manual model work must fit the approved total. Confirm enforcement at the actual admission path before enabling work; stop workers/cancel queued work when the budget is exhausted or an ambiguous failure occurs.
5. Jev reserves serialized request bytes plus 131,072 locally; that reservation is not a provider billing cap and TypeSafe requests have no server output-token setting here. OpenAI supports the configured output cap. Record actual usage or explicitly unknown usage; do not advertise a hard dollar ceiling unless the provider/account supplies an enforceable one.
6. Use one disposable Sheet with headers and adequate rows. Suggested mapping: A–J for the existing outward fields, K/L for inward status/notes, M for unrelated manual content and N for an unrelated formula. Keep scheduled sync disabled until its bounded scenario. Test fields are synthetic; the public posting is untrusted matching input.

**Reuse:** Use current settings, workers, queues, browser fixtures, google-auth/httpx and Apprise. Prefer a run sheet plus existing APIs over a second provider client or a generic acceptance framework. If new common infrastructure is genuinely needed, check maintained libraries before building it.

**Done when:** All inputs have owners/private references; budgets and side effects are explicit and enforceable; the sequence maps to current routes/UI; no live call is needed to validate the preparation itself.

**Handoff:** `docs/release/live-acceptance-plan.md` and a sanitized evidence template. Blocks S2; otherwise independent of CI.

## S2 — Execute the current image's live product journey

**Outcome:** Evidence that the actual saved provider clients, independent workers and integrations work end to end inside the accepted image.

**Own:** `docs/release/live-acceptance.md` and isolated test resources. Route discovered source defects to a named module owner; changes require a fresh affected CI/image result before final acceptance.

**Requires:** CI image handoff, S1 approved inputs/envelope and a healthy execution host with browser access. No registry publication is required if the accepted OCI artifact can be loaded directly.

**Instructions and pass conditions:**

1. Claim a fresh owner; correct/reload setup settings; configure/test both models; import/review the synthetic profile; preview filters/source; run a bounded search. Persist source, first-observed and notification timestamps separately. Confirm stored job, run, model/profile revision and review evidence, then restart and resume setup/state.
2. Verify manual generation through official OpenAI Responses, selected/omitted fact IDs and original wording, actual PDF readability/contact information, review/download and authentication after logout. Enable automatic policy for the bounded eligible set, observe its outcome, disable it and confirm manual generation remains available. Repeated identical requests may use the cache and must not be counted as new live model evidence.
3. Deliver the authorized settings test, alert/PDF and digest to the chosen inbox. Check both application acceptance and actual receipt/attachment. Use distinct eligible job membership for alert and digest so deduplication does not make the digest empty. Disable delivery after the scenario. Test uncertain-send/crash windows with the retained synthetic tests, not deliberate duplicate real mail.
4. In Sheets, test access, select/save/test current tab/mappings, preview and write/readback two stable IDs. Repeat to prove no duplicates; preserve the formula/manual cells; stage and review inward changes; revoke only the disposable service account's access and verify an actionable failure without lost local work. Restore access only within the approved sequence. Synthetic partial-HTTP-failure tests remain separately labeled.
5. Exercise independent skip paths for SMTP and Sheets, mark/undo Applied, stale revisions and settings-error links without lost drafts. Prove collection remains usable while an optional integration is disabled/failing. Reuse CI recovery evidence where applicable; perform the operator-visible restart/restore checks on this installation with side-effect workers safely disabled.

**Evidence:** Commit/image identity, date, host/runtime, exact model/connection/profile revisions, sanitized job/run/document IDs, measured/unknown usage, queue outcomes, receipt confirmation, Sheet before/after cell checks, restart results and all errors. Do not store keys, passwords, real inbox addresses or full provider payloads in committed reports.

**Done when:** Every live scenario passes or is explicitly unresolved; no mock is described as live evidence. Model-derived rejections still route to review. Blocks S4 publication and S6 release.

## S3 — Finish browser, resource and operating-trial acceptance

**Outcome:** A measured support/performance statement for the shipped image and a resolved acceptance-trial requirement.

**Own:** `docs/release/support-measurements.md`, QA cases and narrowly scoped measurement helpers. Coordinate with the CI owner before modifying `deploy/container-smoke.py`; do not concurrently edit its workflow.

**Context:** R5/R6 in `agents/release-repair-subtasks.md`; `docs/implementation-plan.md` Step 12; `docs/repairs/combined-verification.md`; current `web/tests/` and `deploy/container-smoke.py`.

**Instructions:**

1. Declare exact browsers/versions first. Test the serving container at desktop, 320px and 390px, keyboard-only navigation, visible focus, dialogs, errors, status announcements, job deep links and conflicting/dirty settings. Run a real screen reader on a declared environment; automated accessibility checks alone do not close this gate.
2. Seed 10,000 synthetic jobs for the actual authenticated list/filter/sort/detail workflow. Record API timings and browser behavior with hardware, sample size and cold/warm conditions. The existing large CSV export test is not evidence of interactive performance. Preserve the existing 200 KB compressed-JavaScript budget and measure actual HTTP compression/cache behavior.
3. Consume CI image size/start/idle measurements. Add missing configured-run/PDF peak memory, CPU/disk headroom, build duration and sampling context. The current runner initializes `run_memory`, `render_peak_memory` and `pull_seconds` to null, so a green report alone does not close these measurements. Registry pull timing belongs to S5 after candidate publication.
4. Reconcile Step 12 with the current product before sign-off: retain and run a representative 24-hour schedule/cadence trial, or record an explicit owner-approved first-release scope change. If retained, use approved sources/role families and an isolated synthetic profile, separate caps for the longer run and a permitted notification destination. Measure discovery/check cadence, decision-to-alert and decision-to-PDF receipt including queue time. The old 30-second alert and p95 two-minute PDF targets are unmeasured, and scheduled digest delivery must be measured against its selected delivery window. Retire obsolete Resume Matcher/Dot/local-model instructions rather than testing removed paths.
5. Use synthetic failure injection for provider outages, worker crashes, timeouts and invalid PDFs; preserve live transport evidence separately. Confirm every selected opportunity has a delivered result or inspectable recoverable/final outcome. Set minimum/recommended resources only from measurements, and list sample-size limitations for percentile claims.

**Reuse:** Existing Playwright suites, browser accessibility tools, container stats and application timestamps; no new telemetry service is needed. Existing library/tool research is required only if these cannot obtain the specified measurement reliably.

**Done when:** Support claims match observed versions/hosts, accessibility checks have evidence, missing metrics are populated or explicitly scoped out, and the Step 12 requirement has an explicit disposition. Preparation can run now; image QA waits for CI and live/trial observations depend on S1/S2. Blocks S6; pull measurement completes in S5.

## S4 — Package and publish a reviewable release candidate

**Outcome:** A licensed, traceable candidate image and a working versioned hosted installer bundle.

**Own:** License/notice/security files, package license metadata, a new promotion/bundle workflow, hosted bootstrap, and distribution documentation. Coordinate edits to `deploy/install.sh`/installer helpers with S5. Do not replace the active CI owner's workflow while it is being repaired.

**Requires:** Owner identity/distribution decisions. Local packaging can start now; actual image inventory and candidate publication wait for CI and applicable S2/S3 technical gates plus publication authorization.

**Instructions:**

1. Add the selected root license and matching Python metadata, required copyright/contribution terms, private security-reporting route and supported-version policy. Audit source/template/fixtures/design assets and actual runtime Debian/TeX/font notices against `docs/redistribution-inventory.json` and the image SBOM. Metadata assertions alone are not the artifact review.
2. Package all five current deploy files plus the root MIT `LICENSE` notice: `install.sh`, `install.py`, `pipeline_runtime.py`, `pipeline_management.py`, `internship-pipeline`, `LICENSE`. The present shell file only finds adjacent files and refuses a missing bundle; uploading it by itself does not create a hosted installer.
3. Implement the smallest version-pinned download/verify/extract/launch path for that bundle. Reuse Python 3.12 stdlib/current helpers; reject failed downloads, altered archives, unsafe extraction paths and missing files before execution. Make the chosen checksum/attestation verification and trust source explicit. Do not invent a live URL before publication.
4. Use existing OCI candidates and their attestations to publish accepted architecture images and the combined manifest, verifying the relationship between tested platform content, exported artifacts and registry digests. Record source SHA and digests in release metadata; final promotion must not rebuild different bytes.
5. Publish the installer archive, checksums and release metadata as a candidate; pin its image reference and exact supported matrix. Verify access from a clean account/environment appropriate to the public/private release decision. Test the published bytes again in S5.
6. Update README/install/privacy/support documentation around the actual contract, resource measurements, provider limits and recovery behavior. Historical reports stay historical; current release claims must name the new evidence.

**Acceptance:** Deterministic complete bundle; corruption/incomplete-download/extraction checks; no private fixtures, tokens, generated session output or host configuration in archives/image; actual image notices inspected; downloadable immutable/versioned references; registry platform identities traceable to CI.

**Handoff:** `docs/release/distribution.md`, candidate URLs/digests, notices/security policy and exact hosted command. Blocks S5. Select only established artifact/registry tooling after checking its current docs; do not build a custom signing or package system.

## S5 — Prove installation, management and recovery on advertised hosts

**Outcome:** Evidence from the exact hosted command and accepted artifacts, including complete recovery by an unfamiliar operator.

**Own:** `docs/release/installation-acceptance.md`, installation/management acceptance cases, and fixes in `deploy/install.py`, `pipeline_runtime.py`, `pipeline_management.py` after coordinating with S4's bundle freeze.

**Requires:** S4 published candidate, available hosts and an operator who did not implement the installer. Check each proposed host/runtime cell or narrow the advertised matrix explicitly.

**Matrix distinction:** CI's Linux amd64/arm64 × Docker/rootless Podman smoke results do not prove host installation. Linux installer acceptance needs those four combinations if claimed. macOS adds Intel/Apple Silicon × local Docker Linux VM/Podman machine, also four combinations if claimed. A real Podman machine must prove saved loopback SSH identity and port forwarding. Windows/remote engines remain outside the current contract. Record actual OS/runtime versions and SELinux behavior where applicable.

**Instructions and pass conditions:**

1. Start without a checkout; run the exact hosted command with Python 3.12+ and the declared runtime dependency. Verify missing/stopped/multiple-runtime guidance, port collision, owner-only paths, volume permissions, readiness URL and token/claim flow. Runtime installation/VM startup is currently guided rather than automatically performed; documentation must say so.
2. Test interrupted pull/create/start, same-data rerun, stopped owned container, missing owned container with retained volume, missing-volume refusal, custom installation/command paths and saved endpoint/context. Confirm no second installation or empty replacement volume appears.
3. Remove access to the source checkout and exercise the installed command: status, start, stop, URL, bounded sanitized logs, authenticated diagnostics and stopped-only owner/token recovery. Verify jobs/settings/documents survive.
4. Measure cold pull and start with network/cache/host details. Feed observed requirements back to S3/S4.
5. Back up both DBs, the exact encryption key, uploads/provenance and PDFs; restore into fresh storage using the exact same image; verify owner login, revoked sessions, readable documents and no replay of confirmed delivery/sync. Preserve the original stopped installation until the restored one is verified.
6. Resolve the current operator gap: container smoke restores into `/var/data/restored`, but the installer/manager only registers `/var/data`. Write and execute a complete supported destination configuration/management procedure. If the first-release recovery promise requires the installed command to manage that restored instance, implement and test the shared manifest/runtime contract before calling recovery complete. A passing one-off smoke restore cannot stand in for this.
7. Resolve the update wording in R9: no automatic update or cross-release schema/downgrade compatibility exists. For the first release, document fresh installation and exact-image recovery, explicitly excluding upgrades from development snapshots. Do not claim a tested cross-version update path or add a migration layer. Any broader update promise needs its own approved requirement and acceptance.
8. Have the unfamiliar operator reach the first useful job and complete recovery using only the shipped documentation. Correct omissions and rerun affected checks.

**Handoff:** Per-cell host/runtime evidence, measured pull/start data, operator obstacles/fixes and supported recovery commands. Any bundle/source change returns the affected artifact to S4 and its relevant CI/tests before repeating hosted acceptance. Blocks S6.

## S6 — Reconcile evidence and promote the exact candidate

**Outcome:** Final release status backed by source, artifact and operator evidence.

**Own:** Final updates to `docs/release-readiness.md`, `docs/task-breakdown.md`, `docs/implementation-plan.md`, README and the release evidence index. Coordinate these shared documents after the other task reports settle.

**Instructions:** Map every matrix row to S2–S5 or CI evidence; record exact source/artifact identities and dates; verify all required support cells, credential privacy, notices/security contact and documentation. Do not count repeated subsets as additional tests. Resolve stale Step 12 requirements and the restoration/update wording explicitly. Unpassed required gates remain open; reduce a support claim only by a deliberate scope decision, not by silently omitting its test.

**Done when:** No required acceptance row is unresolved, the unfamiliar-user run passes, selected release contracts match actual behavior and publication is authorized. Promote the exact tested artifacts; repeat affected gates if bytes change. Return public release references and final measured limitations.

## Deferred from the first release

Automatic model-derived rejection is not required while all such outcomes go to review. Enabling it needs fresh representative independently human-adjudicated data, a frozen tuning/untouched evaluation split, at least 300 eligible examples with zero false rejection, at least 30 rejection examples at 98% precision, 95% review recall and 20 ranking comparisons at 80% agreement. Previously inspected examples cannot become fresh evaluation evidence. This is a separate quality project and paid-test authorization, not a connection probe.

Unrestricted resume rewriting, custom model endpoints, remote engines, Windows, automatic updates and cross-release database compatibility are outside the current first-release contract.

## Suggested next work

The local implementation and independent reviews are recorded in [downstream completion status](../docs/release/completion-status.md). S1 is prepared; S3/S4/S5 implementation and native checks are complete within their stated scope. S2 live execution, image/host measurements, hosted acceptance and S6 promotion remain open. Execute them only after the final image handoff and concrete private inputs are ready. This brief does not authorize paid requests, messages, remote Sheet changes or publication.
