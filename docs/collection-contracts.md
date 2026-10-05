# Collection contracts and validation evidence

## Installed versions

Implementation inspected and exercised against **ats-scrapers 0.3.0** and
**python-jobspy 1.2.0**. The installed source is authoritative when its interface
differs from current documentation. Context7 was resolved before querying the
primary project documentation:

- [ats-scrapers source and public API](https://github.com/stapply-ai/ats-scrapers)
- [JobSpy source and public API](https://github.com/speedyapply/JobSpy)

The core modules import scraper dependencies lazily. The normalizer, scheduler
cadence policy and CLI can import without them; calling a scraper still requires
the selected dependency. Sources belong in the package's optional `sources` extra.

## S3: ATS snapshots and normalized identity

`await fetch_company(company, timeout=30)` delegates to the actual
`get_scraper_for_url(..., timeout=..., include_descriptions=True).afetch()` API.
The timeout bounds the entire async operation. `fetch_companies(companies,
timeout=30, concurrency=4)` yields `(Company, FetchResult)` as boards finish and
cancels remaining tasks if its consumer exits.

Ashby, Greenhouse and Lever were inspected in the installed version: each returns
one uncapped full-board JSON response, with descriptions in that response. A
delegating transport wrapper checks that the response contains the expected jobs
list, preventing a malformed HTTP 200 from becoming a valid empty snapshot. It
uses the library's public `Fetcher.request(..., handled=...)` API, preserves 429
and 5xx metadata, and disables immediate library retries so persisted scheduling
can own backoff. A provider's numeric or HTTP-date `Retry-After` survives in
`FetchResult.retry_after_seconds`; 429 without a usable header gets an explicit
local 60-second cooldown.

Other installed providers still run their real library scraper and retain valid
jobs, but return `complete=False, coverage_limited=True` until pagination and
failure behavior are audited. Invalid rows, repeated identities, rate limits,
timeouts and actual failures produce `coverage_limited=False`. Only complete
snapshots may infer closure. Parent ingestion baselines observed rows even in
partial snapshots, so subsequent observed additions can progress while coverage
continues to report its limit. This adapter does not persist baselines or events.

Source identity uses `ats_id`, falling back to the stable posting URL rather than
the library's randomly generated `global_id` fallback. Company names come from
the configured company. Secondary Ashby locations and explicit compensation and
deadline fields are retained. Greenhouse's library `posted_at` conflates
`first_published` and an `updated_at` fallback without exposing which was used,
so `timestamp_kind=source_time_ambiguous`. Ashby and Lever use `published`; absent
timestamps stay unknown. Observation timestamps belong to persistence.

`canonical_url(url)` removes only known tracking parameters and normalizes the
host/default port. It preserves generic routing details, including query order,
duplicate parameters, blank values, escape sequences, path case, trailing slashes
and fragments. The exact `/tenant/requisition/apply` path on Lever and
`/tenant/requisition/application` path on Ashby normalize to the listing for
opportunity identity. The original `SourceJob.apply_url` remains the actual
application endpoint for notifications. Credentials and non-HTTP(S) URLs are
rejected. `content_hash(posting)` includes material content and application
identity but excludes source provenance and timestamp noise.

## S8: scheduling interface

- `interval_for(target: Company | SearchQuery, settings: Settings) -> float`
  selects independent priority-board, standard-board and search cadences.
- `next_due(now, interval_seconds, failures=0, retry_after_seconds=None,
  jitter_fraction=0.1, random_value=0.5) -> datetime` uses exponential backoff
  capped at six hours and never schedules before a server cooldown. Inject the
  random value for deterministic tests and actual jitter in the collector.
- `is_due(due_at, now)` and `overdue_seconds(due_at, now)` support operational
  coverage reporting.
- `provider_key(company)` uses actual URL resolution to group portal subdomains
  under their provider; explicitly configured providers already supply the key.
- `ProviderBudget(max_requests, window_seconds, window_start=None, used=0,
  cooldown_until=None)` provides `admit(now, cost=1)`,
  `defer_until(now, cost=1)` and `cooldown(now, retry_after)` independently per
  provider. Persist its ordinary state if used across restarts.

Parent orchestration owns durable schedules, locks and provider slots. Healthy
`coverage_limited` responses reset failure backoff while remaining visible as
incomplete coverage. Budgets accept explicit estimated costs for pagination and
detail fetches. The libraries expose no universal per-request meter, so exact
wire request counts and negotiated provider limits are not claimed. The three
audited full-board providers use one request with immediate retries disabled;
JobSpy descriptions and other ATS providers can require many requests.

## S9: JobSpy process boundary

`fetch_search(query, timeout=60)` starts a child Python process and exchanges typed
JSON through stdin/stdout. `subprocess.run` kills and reaps the process if the
wall-clock deadline expires, including its blocking scraper threads. This does
not occupy the ATS event loop. The caller must invoke synchronous search work
outside that loop. Unsupported/empty sites are rejected before starting a child.

The worker calls actual `scrape_jobs(site_name=..., search_term=...,
google_search_term=..., location=..., country_indeed=..., hours_old=...,
results_wanted=..., description_format='markdown', fetch_description=True,
verbose=0)`. Version 1.2.0 deprecates `linkedin_fetch_description` in favor of
`fetch_description`; the new field is used. No `job_type` is passed alongside
`hours_old`, avoiding documented board-specific filter conflicts. The source is
exactly `jobspy:{site}`; `board_id` is the configured search ID.

Direct URLs are source-provided and retained for applying, not independently
employer-verified. Dates are labeled `aggregator_date`, so they cannot prove a
posting was newly published. Missing cells and NaN values stay missing. JobSpy
sometimes logs HTTP failures instead of raising; the worker captures its actual
non-propagating logger errors and marks the result incomplete. Caps are checked
per requested site, and cap/empty-coverage diagnostics are distinguished from
transport failures using `coverage_limited`. A successful uncapped search means
the requested query completed, not that the broader market was exhausted.

Configure narrow role-family/location queries with overlapping recent windows.
Capped queries retain results and report the need to partition; automatic
geographic partitioning is intentionally not invented without candidate
locations. Persist explicit partitions as separate SearchQuery records. Use one
site per query when independent site failure accounting is needed, since a
library exception across several sites can discard its merged response.

## S10: company validation and daily discovery

`resolve_board(company) -> BoardValidation` performs an offline check using the
actual installed URL resolver and registered scraper constructors.
`await validate_company(company, timeout=30) -> BoardValidation` then fetches a
board and sets `verified=True` only for a complete successful snapshot. Unsupported
custom domains are reported without fabricating slugs or adapters.

`discover_companies(name=None, limit=200, timeout=30) -> list[Company]` uses actual
`Client.companies()` or `Client.find_company(name, limit=...)` against the library
directory. It preserves real directory URLs and filters unsupported adapters.
`candidates_from_jobs(jobs)` recognizes actual supported employer URLs from source
postings and produces company board URLs for the three audited providers.
Candidates start `enabled=False, priority=False`; discovery never invents user
priority or verifies internship relevance. Parent persistence owns validation,
enabling, baseline ingestion and refresh timing. Run synchronous directory
discovery in the daily discovery role, independently of fast polling.

The directory is a source for approximately 100–200 candidates, not a claim that
100–200 relevant companies have been checked or enabled. Live directory refresh,
large-registry coverage and personal candidate relevance remain operational work.

## Validation evidence — October 5, 2026

- A public read-only Ashby OpenAI board fetch through `fetch_company` returned
  **827 identifiable jobs**, `complete=True`, no error, and nonempty descriptions.
  This is live ATS contract evidence, not an internship relevance trial.
- A public read-only JobSpy Indeed query for `software engineer internship` in
  `Denver, CO`, `results_wanted=1`, `hours_old=72` completed through the child
  process but returned no rows. Its coverage was explicitly unverified; no live
  JobSpy posting-field success is claimed.
- Focused offline tests exercise installed ATS parsing with synthetic transport
  responses, malformed payloads, duplicate identity, timeouts, completed-board
  streaming, Retry-After, material revisions, cross-source application identities,
  provider isolation, budgets, result caps, logged errors, real process killing,
  registry resolution and disabled directory candidates.
- Ruff and mypy run against owned source files; targeted pytest runs on the
  shared Python 3.12 environment and the isolated scraper environment. No actual
  candidate data, credentials, notification delivery or deployment is involved.

Library limitations remain explicit: only three ATS snapshot implementations are
audited for completeness; some library descriptions are truncated at 25,000
characters; Greenhouse timestamp distinction is unavailable; JobSpy coverage and
direct employer URL ownership cannot be proven from its return contract alone.
