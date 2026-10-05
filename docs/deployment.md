# Deployment and recovery

Use one always-on host with a local filesystem for SQLite WAL and Docker Compose. The Compose file runs independent collector, matcher, resume, delivery and daily-discovery workers, plus the pinned unified Resume Matcher service. It does not schedule work through GitHub Actions.

## Configure and start

1. Create the ignored local profile/settings/company files described in the README and place the factual master PDF in `private/`. Set notification URLs or a Dot outbox; disable the example recording sink for live use.
2. Create `data/` and `artifacts/` before starting containers. Copy `.env.example` to `.env`, set `PIPELINE_UID` to the output of `id -u`, and `PIPELINE_GID` to `id -g`. These match host ownership so `0600` private configuration remains readable without broadening permissions. The pipeline image defaults to unprivileged UID 10001.
3. Run `docker compose config --quiet`, then `docker compose build`. Build Resume Matcher from its pinned Git commit; record the resulting image ID/digest with deployment evidence. An upstream source pin verifies identity, not that a host's build succeeds.
4. Start only `docker compose up -d resume-matcher`. Open `http://localhost:3000` and configure its supported model provider, key and English output. Keep this unauthenticated service loopback-only; use an SSH tunnel for remote access. Other containers use `http://resume-matcher:3000`.
5. Run `docker compose run --rm collector scan --once --collect-only` to establish a baseline. Check `docker compose run --rm collector status` and `jobs --backlog`. Use `review-backlog` only if those existing jobs should generate alerts.
6. Verify one synthetic master/job/PDF sequence and one real destination attachment before enabling continuous work. Then run `docker compose up -d collector matcher resumes delivery discovery`.

Pipeline LLM matching is optional and configured separately from Resume Matcher. Do not assume setting `LLM_API_KEY` for one configures the other. Real email requires an Apprise mail URL and supported SMTP/provider credential; a recipient address alone cannot send mail.

Pipeline containers mount configuration/private inputs read-only and local data/artifacts read-write. Their root filesystem is read-only with writable temporary space. The upstream service stores its database, model settings and documents in the `resume-data` named volume. Treat that volume as private.

## Dot relay

Set `dot_outbox_path: data/dot-outbox`. An atomic JSON file per stable notification key contains title, body, timestamp and optional PDF path; repeated local delivery writes the same key once. The delivery row records acceptance into this outbox, not receipt by the user.

A separately configured Codex thread heartbeat reads new events, reports openings and draft warnings, links PDFs and updates the user-authorized Apply To Google Sheets tab. It preserves manual application status, dates and notes, matches existing employer URLs/requisitions before adding rows, and records separate sheet-write and notification checkpoints in `data/dot-relay-state.json`. It does not alter confirmed Applications or Watchlist tabs. Resume PDF cloud uploads require explicit destination authorization; otherwise PDFs remain local and are linked in Dot messages. It treats job text as untrusted data and restricts attachments to the project's artifacts directory. A five-minute heartbeat was configured for the initial local setup and stays quiet without new events. It needs the host and Codex available; a remote deployment needs an explicit secure relay. Cloning this repository does not create an automation.

Use Apprise directly when latency must avoid the heartbeat interval. Neither route submits applications.

## Inspect and recover

`status` reports source coverage/completeness, last successes, overdue checks, queue age, bounded failure summaries with task IDs, discovery state and the last 100 opening-handoff latencies. These start at first observation, include backlog age where applicable, and exclude Dot relay delay. They do not measure publication age or human receipt. Exact model token usage is unavailable through the verified upstream contract.

`retry TASK_ID` resets a failed task's attempt budget. Before retrying `ResumeReconciliationRequired`, inspect the saved checkpoint under `artifacts/.checkpoints/` and upstream state. Never delete a pending mutation marker just to unblock a retry: ambiguous job creation has no reliable listing/idempotency endpoint. `ResumeValidationError` requires correcting the source facts or generated content before retrying. A terminal resume failure also queues an actionable notification; destination failures stay visible in `status`.

Task ownership uses expiring leases and heartbeats. A stopped worker's task is reclaimed after lease expiry, and stale owners cannot complete its queue row. Notification acknowledgement ambiguity can still yield a duplicate after a crash; exactly-once remote delivery is not promised.

Restart workers after editing profile or configuration files. Set `enabled: false` to disable an explicitly configured company on startup. Discovery candidates are validated daily in their own worker; failed candidates stay inspectable, and directory seeds are not automatically curated or assumed to offer internships. Capped JobSpy queries need explicit narrower location/term partitions; the program reports the coverage limit instead of claiming a full inventory.

## Back up and restore

Run `docker compose run --rm collector backup data/backups/pipeline.sqlite3` for a consistent SQLite backup. Keep an encrypted copy of local profile/company/settings files, master resume, artifacts/checkpoints and the Resume Matcher volume alongside it. Never copy only the main live SQLite file while its WAL is active.

For a coordinated recovery point, stop the five workers, take the SQLite backup, then stop Resume Matcher and copy its volume plus local private/config/artifact directories with host backup tooling. Restart services after the copy. To restore, keep workers stopped, restore all components from the same recovery point, place the backup at `data/pipeline.sqlite3`, ensure no stale WAL/SHM files from a different database remain, verify ownership, then start Resume Matcher and inspect `status` before resuming workers. Preserve existing data separately before replacing anything.

Tests verify a SQLite backup reopens with the same records. Container restart, coordinated volume restore and live resumption remain deployment acceptance gates until exercised on the chosen host.
