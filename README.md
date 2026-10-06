# internship-pipeline

Find SWE, product management, ML/AI and data science internships, send an opening alert, then deliver a fact-checked resume draft and the original application link. The user reviews and applies.

The package, independent workers, persistence, integrations and offline workflow are implemented. Live model/PDF delivery and the 24-hour performance trial require configuration and verification; see [acceptance results](docs/acceptance-results.md) for exact evidence.

```text
ats-scrapers ─┐                  ┌─ opening notification ─────────────────────┐
             ├─ SQLite → match ─┤                                           ├─ user applies
JobSpy ──────┘                  └─ Codex LaTeX edits → pdflatex/PDF checks → PDF ┘
   └─ candidate boards → daily validation → direct polling
```

Collection, matching, generation, delivery and daily discovery run as separate processes. A slow model or failed notification cannot hold up company checks. Notifications use Apprise, or a local outbox connected to a Codex Dot heartbeat.

## Try the complete offline workflow

```sh
uv sync --python 3.12 --frozen
uv run internship-pipeline demo
```

The demo uses synthetic data, writes one opening event and one synthetic PDF event, then repeats ingestion to verify no duplicates. It sends no external messages and does not call Codex or compile personal resumes. Its PDF is labeled as a demonstration.

## Browser setup

Run `docker compose up --build -d`, read the one-time owner setup token with `docker compose logs app`, and open `http://localhost:8080`. Account setup and login work before a profile or model is configured. The single-container app uses persistent owner sessions; see [deployment and recovery](docs/deployment.md) and [current dashboard capabilities](docs/dashboard.md). Profile and Job Filters settings save immutable SQLite revisions; workers read the next revision between tasks. AI Models has independent connection configuration and synthetic capability tests; authoritative Jev evaluation and résumé generation are subsequent slices.

## Existing operator worker configuration

```sh
mkdir -p private data artifacts
cp config/companies.example.yaml config/companies.local.yaml
cp config/settings.example.yaml config/settings.local.yaml
```

Maintain supported facts, education, availability and eligibility in browser Settings → Profile; maintain mandatory constraints and soft preferences in Job Filters. YAML no longer supplies candidate data. Existing personal files are left untouched: explicitly back them up, remove `profile_path` from operational settings, and review/re-enter supported facts in the browser. There is no automatic import or fallback. Source configuration remains operational YAML pending the search configuration task. Set companies to real board URLs and `enabled: true`; optional broad searches go in `config/searches.local.yaml` and are enabled by `searches_path`. Example queries need their locations/country adjusted explicitly.

For Apprise, put notification URLs in the ignored settings file or `PIPELINE_NOTIFICATION_URLS` as a JSON array. Use a service supporting PDF attachments. For Dot, set `dot_outbox_path: data/dot-outbox` and configure the [local relay](docs/deployment.md#dot-relay). Set `recording_notifications_path: null` for either live transport. A recording transport is only an offline test sink.

The legacy generation modules remain covered by offline regressions, but the browser application keeps matching, generation and delivery workers inactive until their supported integrations are implemented. Saving a profile or model connection does not enable those legacy paths. See the [same-origin dashboard](docs/dashboard.md).

```sh
uv run internship-pipeline --config config/settings.local.yaml scan --once --collect-only
uv run internship-pipeline --config config/settings.local.yaml jobs --backlog
uv run internship-pipeline --config config/settings.local.yaml review-backlog
uv run internship-pipeline --config config/settings.local.yaml scan --once
```

The first inventory of each board becomes an explicitly labeled backlog, so old jobs are not presented as newly posted. `review-backlog` opts into assessing them. Subsequent new jobs enter the pipeline automatically while workers run.

## Continuous operation and controls

Use [Docker Compose setup and recovery](docs/deployment.md) for continuous operation. The five worker roles are `collector`, `matcher`, `resumes`, `delivery` and `discovery`; each supports `--once`. `scan --once` is useful for manual runs, but continuous workers provide latency isolation.

```sh
uv run internship-pipeline status
uv run internship-pipeline jobs
uv run internship-pipeline add-company acme Acme https://jobs.ashbyhq.com/acme --priority
uv run internship-pipeline discover --seed --limit 200
uv run internship-pipeline refresh-discovery
uv run internship-pipeline retry TASK_ID
uv run internship-pipeline mark-applied JOB_ID
uv run internship-pipeline backup private/pipeline-backup.sqlite3
```

Pass `--config config/settings.local.yaml` before commands when using local settings. Directory entries are unverified candidates; daily validation enables supported working boards. Directory order does not establish internship relevance. To stop a configured company, set `enabled: false` and restart the collector; deleting its YAML row does not remove persisted history or disable it.

## Timing and correctness

- Priority boards default to five-minute polls, ordinary boards to 15 minutes and JobSpy queries to 60 minutes. Configured minimums are two, five and 30 minutes respectively. Backoff, cooldowns and actual provider availability can increase these intervals.
- Only Ashby, Greenhouse and Lever have audited full-board snapshot contracts. Incomplete responses can add observations but cannot close jobs. Closure needs two complete misses, and stale aggregators cannot reopen directly closed jobs.
- Delivery is locally deduplicated and retries reuse saved PDFs. An ambiguous remote acknowledgement can still cause an occasional duplicate. Dot outbox acceptance is distinct from the heartbeat actually notifying the user.
- Explicit unsupported qualifications and protected factual changes block the PDF. Successful drafts still carry semantic review warnings because automated checks cannot prove every paraphrase preserves meaning.
- Provider or profile changes invalidate generation fingerprints. Changed descriptions are reassessed; stale generation results and queued attachments are suppressed. Applications are marked submitted only by `mark-applied`.

These are polling settings, not publication-to-delivery guarantees. A Dot relay running every five minutes adds up to five minutes after local outbox creation and depends on the local app/host being available.

## Development and evidence

```sh
uv run ruff check src tests
uv run mypy src/internship_pipeline
uv run pytest -q
uv build
docker compose config --quiet
```

See [implementation progress](docs/implementation-plan.md), [integration contracts](docs/integration-contracts.md), [design](docs/design.md), [acceptance results](docs/acceptance-results.md) and [agent guidance](AGENTS.md). Private documents, generated PDFs, database files, local configuration and credentials are Git-ignored and excluded from the Docker build context.
