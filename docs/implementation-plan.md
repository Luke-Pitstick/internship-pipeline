# Stepped implementation plan

Prepared October 5, 2026. Core implementation and offline acceptance are complete; live deployment/model/delivery verification and the 24-hour trial remain open. See [acceptance-results.md](acceptance-results.md) for evidence and limits. This document is the implementation checklist; [design.md](design.md) contains the supporting architecture and behavior.

## Delivery rules

Build in sequence. Each step names its dependency, intended files, concrete work and acceptance gate. Keep the pipeline working as capabilities are added. Do not introduce alternative databases, generic plugin systems or a custom dashboard for this single-user workload.

Unchecked items include live acceptance gates and documented limits, not silently completed work. The initial 200 directory entries are candidate boards, not a curated set of internship employers. Five separate worker roles (including matching and discovery) strengthen the original three-role isolation.

Use Python with a `src/internship_pipeline/` package, `uv` for environment/lock management, pytest for behavior tests and Ruff for formatting/linting. Pin verified dependency versions during step 1. External services are accessed through narrow clients, and only integration checks need network access or credentials.

The first complete product is step 6: scan a few company boards, identify relevant internships, send opening details, generate a tailored PDF and deliver it. Steps 7–12 add unattended operation, broader discovery and operational verification.

## Step 1 — Establish the package and verify tool contracts

**Depends on:** repository scaffold.

**Files:** `pyproject.toml`, `uv.lock`, `.env.example`, `src/internship_pipeline/cli.py`, `tests/integration/`, `tests/fixtures/`, `docs/integration-contracts.md`.

- [x] Create the installable Python package, CLI entry point and lint/test commands.
- [x] Install and pin ats-scrapers, python-jobspy and Apprise; pin a tested Resume Matcher deployment version.
- [ ] Fetch one supported ATS board and run one narrow JobSpy query, recording identity fields, descriptions, pagination and timestamp semantics.
- [ ] Verify Resume Matcher's actual installed API sequence using a synthetic master resume and sample job description: import, add job, tailor and download PDF.
- [ ] Verify PDF attachment delivery with Apprise once the user supplies a destination. Before that, exercise a recording test transport and leave live delivery explicitly unverified.
- [x] Document timeouts, error responses, authentication and supported inputs from the actual versions; do not implement against an assumed README contract.

**Acceptance:** the CLI runs; a supported board returns identifiable jobs; the tailoring contract yields a readable PDF; each integration's verified/unverified status is explicit. No real credentials or candidate documents enter committed fixtures.

## Step 2 — Define candidate data, job records and persistence

**Depends on:** step 1.

**Files:** `models.py`, `config.py`, `storage.py`, `config/profile.example.yaml`, `config/companies.example.yaml`, `tests/test_storage.py`.

- [x] Define typed records for candidate constraints, factual experience, role-family views, companies, canonical jobs, source observations, match results, resume artifacts and deliveries.
- [x] Give experience facts stable IDs and the candidate profile a revision hash. Unknown location, eligibility or term inputs remain unknown.
- [x] Create the SQLite schema with WAL mode and short transactions. Persist source publication/update times separately from first/last observation.
- [x] Add uniqueness constraints for source observations, artifact generation keys and per-destination delivery events.
- [x] Load personal configuration from ignored local paths and secrets from environment variables.

**Acceptance:** records survive restart; repeated ingestion does not duplicate the same observation; two distinct requisitions with the same title remain separate; no unprovided preference becomes a rejection rule.

## Step 3 — Collect and normalize direct company postings

**Depends on:** step 2.

**Files:** `sources/ats.py`, `normalization.py`, `collection.py`, `tests/test_collection.py`.

- [x] Implement the ats-scrapers adapter with direct company URLs and bounded async fetches.
- [x] Normalize stable IDs, canonical apply URLs, locations, descriptions and source provenance.
- [ ] Complete pagination, record truncation/failure and process each finished board immediately.
- [x] Baseline a company's first successful snapshot. Store existing matches as backlog rather than claiming they were newly published.
- [x] Recognize new IDs, description edits, verified reopenings and closures. Never infer closure from a failed or incomplete fetch.
- [x] Add `scan --once` for 5–10 configured companies.

**Acceptance:** repeated snapshots emit no duplicate new-job events; one controlled addition emits one event; partial responses cannot close existing jobs; a broken board does not discard successful boards.

## Step 4 — Filter eligibility and explain relevance

**Depends on:** step 3.

**Files:** `matching.py`, `prompts/match.txt`, `tests/test_matching.py`, synthetic labeled job fixtures.

- [x] Apply inexpensive internship/co-op, role-family and confirmed eligibility checks before using a model.
- [x] Cover SWE, product management, ML/AI and data science title variants while inspecting the description for ambiguous roles.
- [x] Add a short structured assessment for plausible matches, including supporting requirement excerpts, matched fact IDs and unknown requirements.
- [x] Classify strong/possible/weak fit. Reject only explicit conflicts with confirmed hard constraints; store the reason.
- [x] Persist match results keyed by job content and profile revision so unchanged jobs are not repeatedly scored.

**Acceptance:** a labeled fixture set handles internship versus full-time roles, product versus project management, explicit degree conflicts and missing work-authorization details. Unknown eligibility is visible, and every accepted match has a concrete explanation.

## Step 5 — Tailor and validate the resume

**Depends on:** step 4 and the verified Resume Matcher contract.

**Files:** `resumes/client.py`, `resumes/service.py`, `resumes/validation.py`, `tests/test_resumes.py`.

- [ ] Import and verify the factual master profile; use role-family views to select relevant projects and achievements.
- [x] Call Resume Matcher through one narrow client, storing its job/resume IDs and generating a PDF for each accepted match.
- [x] Cache artifacts by canonical job, relevant description hash, profile revision and generation configuration.
- [x] Check protected facts and unsupported skills against the factual profile; flag questionable rewrites for review.
- [ ] Validate readable PDF text, expected sections and contact fields, page count and obvious overflow. Visually verify the chosen template with representative samples.
- [x] Save a change summary and artifact metadata. Never treat the upstream resume tracker's status as evidence of an application submission.

**Acceptance:** a representative job produces a readable tailored PDF with a change summary; a repeated request reuses it; changed dates or unsupported qualifications fail validation; malformed PDFs cannot be sent as completed resumes.

## Step 6 — Deliver the first complete workflow

**Depends on:** step 5.

**Files:** `notifications.py`, `pipeline.py`, `tests/test_pipeline.py`, `tests/test_notifications.py`.

- [ ] Add an Apprise transport for the user's chosen destination and verify real PDF attachment delivery after credentials are supplied.
- [x] Compose an opening alert with company, title, location, term, fit reasons, eligibility questions, labeled timestamps and the application URL.
- [x] Deliver the opening alert before generation; deliver the PDF in a second message carrying the same stable job reference and apply link.
- [x] Persist successful delivery events and explicit failure states. Reusing an artifact must not silently send it again.
- [x] Add `scan --once` orchestration from collection through both notifications, with a recording transport for tests.

**Acceptance:** one controlled relevant opening yields one opening alert and one corresponding PDF message. Rerunning the same scan creates neither again. A generation failure leaves the opening alert intact and records a retryable resume failure.

**First product checkpoint:** the complete user workflow works for a small company list. Keep this behavior working through all remaining steps.

## Step 7 — Make work durable and independent

**Depends on:** step 6.

**Files:** `queue.py`, `workers/collector.py`, `workers/resumes.py`, `workers/delivery.py`, storage extensions and recovery tests.

- [x] Store pending tasks atomically with the state transition that requires them.
- [x] Add expiring task leases, bounded retries, next-attempt times and inspectable terminal errors in SQLite.
- [x] Run collection, generation and delivery as separate process roles sharing the same package and local database.
- [x] Reconcile ambiguous Resume Matcher responses before making duplicate drafts; reuse PDFs on delivery retries.
- [x] Handle Apprise failures per destination. Document that ambiguous remote acknowledgement can occasionally produce a duplicate, even with local deduplication.

**Acceptance:** terminate a worker during generation and delivery, restart it, and recover outstanding work. A slow model or unavailable destination cannot delay a scheduled collection check.

## Step 8 — Schedule fast direct checks within provider budgets

**Depends on:** step 7.

**Files:** `scheduler.py`, provider scheduling configuration and scheduler behavior tests.

- [x] Persist per-company due times and prevent overlapping checks.
- [ ] Start priority boards at five minutes; shorten healthy, verified providers toward two minutes. Check ordinary boards every 10–15 minutes.
- [ ] Add provider-wide request budgets, bounded concurrency, jitter, request timeouts and backoff that honors `Retry-After`.
- [ ] Account for pagination/detail fetches when budgeting. Make overdue checks and incomplete coverage visible.
- [x] Prioritize new strong matches in the resume queue while preventing older work from starving.

**Acceptance:** controlled rate-limit responses slow only the affected provider; due-time and request-budget tests pass; collection cadence remains independent of generation backlog. Record measured detection and processing latency rather than asserting a publication-time guarantee.

## Step 9 — Add JobSpy for wider discovery

**Depends on:** step 8.

**Files:** `sources/jobspy.py`, `config/searches.example.yaml`, cross-source normalization tests.

- [x] Run role-family/location queries every 30–60 minutes in isolated processes with timeouts.
- [ ] Verify board-specific filters and use overlapping recent-result windows; fetch missing descriptions for plausible matches.
- [ ] Detect result caps and partition queries where needed, recording coverage limits.
- [x] Prefer verified employer apply URLs and link duplicates by canonical URL or employer requisition identity.
- [x] Persist new candidate company boards for validation and future direct monitoring.

**Acceptance:** the same job found through an ATS and JobSpy generates one application opportunity; different requisitions remain separate. A hanging JobSpy query cannot block direct polling. Old aggregator additions are not labeled as newly published jobs.

## Step 10 — Expand the company registry and user controls

**Depends on:** step 9.

**Files:** `discovery.py`, CLI commands, company registry data and coverage documentation.

- [ ] Seed approximately 100–200 relevant companies from the available directory and public internship lists.
- [x] Validate discovered boards and installed adapter support before scheduling them. Establish a baseline on addition.
- [x] Add `add-company`, `status`, `retry`, `mark-applied` and an explicit backlog-review command.
- [x] Store priority separately from source discovery. Report unsupported companies without pretending their jobs are monitored.
- [x] Refresh company discovery daily without delaying fast checks.

**Acceptance:** a newly added company begins monitoring, its old jobs form a labeled backlog, and its next new posting follows the normal workflow. The status command distinguishes healthy, delayed, failing and unsupported sources.

## Step 11 — Deploy and expose operational health

**Depends on:** step 10.

**Files:** `Dockerfile`, `compose.yaml`, deployment/backup instructions and health commands.

- [ ] Deploy the three process roles and the supported Resume Matcher service stack on one always-on host.
- [x] Mount persistent local SQLite/artifact volumes; keep credentials and real candidate inputs outside Git.
- [x] Keep Resume Matcher private to the deployment network or behind authenticated access.
- [ ] Add health reporting for collection success, overdue checks, queue age, generation latency, delivery failures and model usage.
- [ ] Verify database/profile backup and restoration. Configure a separate health-alert destination only if supplied by the user.
- [x] Add CI for linting and meaningful offline behavior tests; keep credentialed checks manual or explicitly configured.

**Acceptance:** restarting containers preserves state, generated resumes and pending tasks. A restored backup can resume processing. Healthy and degraded states are visible without reading unstructured logs.

## Step 12 — Run the acceptance trial and calibrate

**Depends on:** step 11 and the user's actual profile/destination/model configuration.

**Files:** `docs/acceptance-results.md` containing sanitized results only.

- [ ] Run a representative 24-hour trial with the configured company list and all four role families.
- [ ] Measure successful-check cadence, match quality, first-seen-to-opening-alert latency and relevance-to-PDF-delivery latency, including queue time.
- [ ] Target opening delivery within 30 seconds of a relevance decision and p95 PDF delivery within two minutes; report misses and their causes.
- [ ] Exercise provider failure, worker crash, model timeout, invalid PDF and notification failure without losing qualified jobs.
- [ ] Review sample matches and resume diffs with the user; correct filters and prompts based on observed errors.

**Acceptance:** every qualified opportunity is delivered or has an explicit recoverable/final error, duplicate notifications are controlled, priority-board coverage is visible, and measured performance meets the agreed targets or documents a concrete limit. The user can use the delivered PDF and original link to apply.

## Inputs needed before personal live operation

- Target countries/locations, internship term, degree/graduation date and work-authorization constraints.
- Factual master resume and any additional supported projects/accomplishments.
- Priority employers and the chosen notification destination with its credentials.
- Supported model provider and credentials or a reachable local endpoint.
- Always-on deployment host and agreed resource budget.

Synthetic integration fixtures allow development to proceed before these are available. They must never be mistaken for the user's real profile or used to send real applications.
