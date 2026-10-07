# internship-pipeline

Find and assess SWE, product management, ML/AI and data science internships, review grounded résumé drafts, and optionally receive email alerts or sync a Google Sheet. The owner records applications explicitly.

The package, independent workers, persistence, integrations and offline workflow are implemented. Live model/PDF delivery and the 24-hour performance trial require configuration and verification; see [acceptance results](docs/acceptance-results.md) for exact evidence.

```text
ATS / JobSpy → SQLite observations → persisted Jev assessments → jobs workspace
                                      ├─ reviewed grounded PDF drafts
                                      ├─ optional email alerts / digest
                                      └─ optional Google Sheets sync / CSV
Owner reviews and applies → explicit Applied record
```

Collection, matching, generation, delivery and daily discovery run as separate processes. A slow model or failed notification cannot hold up company checks. Optional email uses Apprise through the browser SMTP configuration; Google Sheets sync runs in its own server worker. Neither requires a local Codex session or SSH download.

## Browser setup

Run `docker compose up --build -d`, read the one-time owner setup token with `docker compose logs app`, and open `http://localhost:8080`. Account setup and login work before a profile or model is configured. The single-container app uses persistent owner sessions; see [deployment and recovery](docs/deployment.md) and [current dashboard capabilities](docs/dashboard.md). Profile and Job Filters settings save immutable SQLite revisions; workers read the next revision between tasks. AI Models configures independent Jev and general LLM connections. The configured general LLM selects confirmed facts for a job-specific draft; inspect changes, preview/download the PDF and explicitly review it in job detail. Master PDFs use saved facts without a model. See [master rendering](docs/t11-master-resume.md) and [job-specific generation](docs/t12-tailored-resumes.md).

## Existing operator worker configuration

```sh
mkdir -p private data artifacts
cp config/companies.example.yaml config/companies.local.yaml
cp config/settings.example.yaml config/settings.local.yaml
```

Maintain supported facts, education, availability and eligibility in browser Settings → Profile; maintain mandatory constraints and soft preferences in Job Filters. YAML no longer supplies candidate data. Existing personal files are left untouched: explicitly back them up, remove `profile_path` from operational settings, and review/re-enter supported facts in the browser. There is no automatic import or fallback. Source configuration remains operational YAML pending the search configuration task. Set companies to real board URLs and `enabled: true`; optional broad searches go in `config/searches.local.yaml` and are enabled by `searches_path`. Example queries need their locations/country adjusted explicitly.

Configure optional email in Settings → Notifications & Integrations with SMTP host, TLS mode, sender/recipient and encrypted credentials. Choose qualifying-job alerts or a daily digest, inspect delivery status, and explicitly send a test when ready. Configure Google Sheets there with a service-account key, select the shared spreadsheet/tab, preview column mappings and then queue sync. The app preserves unrelated cells and proposes explicitly mapped status/notes changes for owner review. CSV export works without Google. See [email setup](docs/t14-email-alerts.md) and [Google authorization and ownership](docs/t15-spreadsheet-sync.md).

Job-specific generation supports manual requests plus an off-by-default automatic policy under Settings → Resume Generation; see [generation controls](docs/t13-generation-policy.md). Both operate independently of notification delivery. Configure and test the general LLM, save confirmed profile facts, then request a draft in job detail or explicitly enable bounded automation. The Codex subscription/source-edit generator has been removed. See the [same-origin dashboard](docs/dashboard.md).

```sh
uv run internship-pipeline --config config/settings.local.yaml scan --once --collect-only
uv run internship-pipeline --config config/settings.local.yaml jobs --backlog
uv run internship-pipeline --config config/settings.local.yaml review-backlog
uv run internship-pipeline --config config/settings.local.yaml scan --once
```

The first inventory of each board becomes an explicitly labeled backlog, so old jobs are not presented as newly posted. `review-backlog` opts into assessing them. Subsequent new jobs enter the pipeline automatically while workers run.

## Continuous operation and controls

Use [Docker Compose setup and recovery](docs/deployment.md) for continuous operation. Complete stopped-instance backups and fresh-only restore are documented in [operations](docs/t17-operations.md); database-only backups no longer represent full recovery. Worker roles include `collector`, `matcher`, `master-resumes`, `tailored-resumes`, `search-runs`, `email-delivery`, `sheets-sync` and `discovery`; each supports `--once`. `scan --once` is useful for manual runs, but continuous workers provide latency isolation.

```sh
uv run internship-pipeline status
uv run internship-pipeline jobs
uv run internship-pipeline add-company acme Acme https://jobs.ashbyhq.com/acme --priority
uv run internship-pipeline discover --seed --limit 200
uv run internship-pipeline refresh-discovery
uv run internship-pipeline retry TASK_ID
uv run internship-pipeline mark-applied JOB_ID
uv run internship-pipeline backup private/pipeline-backup --data-dir /absolute/persistent/directory
```

Pass `--config config/settings.local.yaml` before commands when using local settings. Directory entries are unverified candidates; daily validation enables supported working boards. Directory order does not establish internship relevance. To stop a configured company, set `enabled: false` and restart the collector; deleting its YAML row does not remove persisted history or disable it.

## Timing and correctness

- Priority boards default to five-minute polls, ordinary boards to 15 minutes and JobSpy queries to 60 minutes. Configured minimums are two, five and 30 minutes respectively. Backoff, cooldowns and actual provider availability can increase these intervals.
- Only Ashby, Greenhouse and Lever have audited full-board snapshot contracts. Incomplete responses can add observations but cannot close jobs. Closure needs two complete misses, and stale aggregators cannot reopen directly closed jobs.
- Email membership and attempt records persist independently of search and generation. Ambiguous SMTP acceptance requires explicit review; deliberately retrying it can duplicate a remote email. Sheets reads stable IDs before writing and preserves verified row checkpoints after partial failures.
- Explicit unsupported qualifications and protected factual changes block the PDF. Tailored drafts preserve selected confirmed wording verbatim and carry review warnings for omitted experience and uncertain eligibility.
- Provider or profile changes invalidate generation fingerprints. Changed descriptions are reassessed; stale generation results and queued attachments are suppressed. Applied status records an explicit owner decision through the workspace, `mark-applied`, or acceptance of a reviewed Sheets proposal; the pipeline never submits applications.

These are polling settings, not publication-to-delivery guarantees. Email digests follow the configured local timezone/hour; remote provider availability and retries can increase delivery time.

## Development and evidence

```sh
uv run ruff check src tests
uv run mypy src/internship_pipeline
uv run pytest -q
uv build
docker compose config --quiet
```

See [implementation progress](docs/implementation-plan.md), [integration contracts](docs/integration-contracts.md), [design](docs/design.md), [acceptance results](docs/acceptance-results.md) and [agent guidance](AGENTS.md). Private documents, generated PDFs, database files, local configuration and credentials are Git-ignored and excluded from the Docker build context.
