# Acceptance results — October 5, 2026

> Historical October 5 evidence and design. The current product uses persisted Jev assessments, authenticated master/tailored drafts, optional encrypted SMTP and independent Google Sheets sync. Resume Matcher, the opening/Dot/recording coordinator and the CLI demo are removed; see [current integration contracts](integration-contracts.md) and [cleanup evidence](integration-cleanup.md).

## Verified

- 195 offline tests pass on Python 3.12, including supported/unknown eligibility, all four role families, source baselines, cross-source identity, conflicting requisitions, partial inventories, closures/reopenings, description edits, durable leases, retries, backup restoration, generation checkpoints, protected facts, unsupported qualifications, unreadable PDFs, stale artifact suppression, per-site cooldown grouping and local Dot outbox idempotency.
- Ruff passes across source/tests; mypy passes across all 25 runtime source modules.
- The synthetic end-to-end demo records exactly one opening and one PDF message, performs one generation, and repeats ingestion with zero extra messages. No external notification or model request is made by this demo.
- Source and wheel distributions build. The Compose definition validates without configuration errors.
- Live read-only Ashby collection returned 827 identifiable postings with descriptions and an audited complete response.
- The installed ATS directory returned 200 distinct supported board candidates after filtering unsupported rows. Those candidates were saved in the initial local database; they are not claimed to be curated or already monitored.
- A narrow live JobSpy Indeed query completed through its subprocess boundary but returned no rows. Live posting fields remain unverified; source contracts and synthetic responses are covered.
- A private current master resume and factual profile were prepared outside Git. Its website download was verified live after a search cache returned an outdated PDF. Summer 2027 and winter 2027 are the supplied term preferences; unprovided eligibility/location constraints remain unknown.
- A native local Dot relay was configured and its saved five-minute schedule verified. It also updates the authorized Apply To spreadsheet tab while preserving manual fields. The requested spreadsheet merge copied 68 opportunities and 23 watchlist entries with readback verification; original source and confirmed application records remained unchanged.
- The relay reports only new outbox events or meaningful failures; outbox acceptance and user notification are distinct stages.
- Independent specification and standards reviews found and corrected stale aggregator reopenings, missing reassessment on edits, provider concurrency/cooldown interference, opening/PDF ordering, stale PDF races, conflicting-requisition merging and unsupported factual additions.

## Live deployment limit

Docker Desktop was started and the actual Compose build attempted. The pinned upstream source resolved, but Docker BuildKit failed while writing `/var/lib/docker/buildkit/metadata_v2.db` with an input/output error. The host data filesystem was 99% full with about 7.5 GiB available at the check. Neither a successful container image nor deployment is claimed. No Docker caches, volumes or user files were deleted to work around the failure.

No model-provider credential was available in the checked task environment. No personal resume was sent to a model, no live tailored PDF was produced and no application was submitted.

## Remaining acceptance gates

1. Build on a host with working Docker storage, record image digests, start the pinned Resume Matcher service and configure its model. Verify installed OpenAPI, synthetic import/job/improve/PDF behavior, and visual rendering with the chosen template.
2. Verify one actual destination notification and PDF receipt. The five-minute Dot relay adds up to five minutes plus app scheduling/availability; it does not meet a 30-second receipt target. Direct Apprise delivery can avoid that extra interval after configuration and measurement.
3. Choose/validate monitored companies and optional location-specific JobSpy queries. The directory seed is only discovery input. Query caps require explicit partitions, and provider-internal pagination/detail-request budgets are library-owned rather than individually instrumented.
4. Exercise container restart and coordinated restore of the database, artifacts, private inputs and upstream service volume. Offline tests simulate lease loss/recovery and restore SQLite state; they are not a live container-crash trial.
5. Run the representative 24-hour trial, measure cadence and actual opening/PDF receipt latency, inspect resume diffs and calibrate matching. The intended 30-second opening and p95 two-minute PDF targets remain unmeasured.

The upstream service selects content from the master and job description. Matched fact IDs/role views are validated and retained as provenance, but a separate pipeline-owned fact-view projection is not implemented. Exact model token usage is not exposed by the verified contract. Automated factual/PDF checks reject known violations but cannot prove semantic equivalence or rule out every visual overlap, so successful PDFs remain drafts requiring review.
