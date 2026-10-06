# Deployment and recovery

Run one application container on a host with local persistent storage for SQLite. The image contains the static Svelte frontend, FastAPI API, Python worker roles, and current résumé tooling. It exposes one port and uses one named volume. The image's Node/Codex runtime remains until the résumé replacement task; Node does not serve the frontend.

## Start and claim

```sh
docker compose config --quiet
docker compose up --build -d
docker compose logs app
```

Open `http://localhost:8080`, copy the **Owner setup token** from the first startup log, and create the owner account with a password of at least 12 characters. Only one claim can succeed, including simultaneous attempts. Claim consumes the token; restarting cannot reopen setup. Account creation works with no model credentials, profile, or notification destination. Keep logs private because the first-boot token authorizes account creation.

Compose binds to loopback by default. To change the local port, set both `PIPELINE_PORT` and `PIPELINE_ORIGIN`, for example `PIPELINE_PORT=8081 PIPELINE_ORIGIN=http://localhost:8081 docker compose up -d`. Always open exactly that origin. Non-loopback HTTP origins are rejected. For remote access, terminate HTTPS at a reverse proxy, keep the upstream container port private, preserve the configured Host header, and set `PIPELINE_ORIGIN=https://jobs.example.com`. HTTPS uses a Secure, HttpOnly, SameSite=Strict `__Host-` session cookie. Local loopback HTTP uses a non-Secure development cookie. Do not expose the local HTTP configuration to the internet.

The container runs as UID 10001, with a read-only root filesystem and temporary `/tmp`. The named `pipeline-data` volume mounts at `/var/data`, containing accounts/sessions, jobs, documents, and operator configuration. The image prepares its ownership for the default user. Back up any existing deployment before changing mounts; this setup does not import or delete previous bind-mounted data. Do not run `docker compose down --volumes` on data you need.

## Account recovery

If a fresh instance's setup token was lost, rotate it locally:

```sh
docker compose exec app internship-pipeline setup-token
```

After the instance is claimed, setup-token refuses to reopen it. Recover its account interactively:

```sh
docker compose exec app internship-pipeline recover-owner
```

The command prompts for the owner username and a new password twice without putting passwords in command arguments or logs. It revokes all sessions and clears login throttles, preserving jobs, documents, and the single account. These commands are local operator operations, with no public recovery endpoint. Outside the container, use `--data-dir /absolute/persistent/directory` after the recovery command name.

## Setup mode and existing worker configuration

`/healthz` means the API process responds. `/readyz` additionally checks SQLite access, built frontend availability, and the supervisor heartbeat. Healthy setup mode is ready even when no worker capability is configured. A worker exit causes the existing supervisor to stop the whole process tree so the host can restart it; graceful shutdown signals entire process groups, including descendants.

Default job storage is `/var/data/state.sqlite3`; accounts live separately in `/var/data/identity.sqlite3`. Existing `/var/data/config/settings.yaml` may continue selecting an existing job database and artifacts. Use absolute paths within the volume and preserve existing inputs. YAML supplies operational source/path settings only. Candidate facts and search constraints/preferences are stored as immutable revisions in the job database and edited in browser Settings. Existing private YAML is never imported or deleted: explicitly back it up before removing obsolete `profile_path` configuration and reviewing/re-entering facts. The Compose service deliberately does not ingest `.env` as worker credentials.

Only configured collection/discovery capabilities launch, and only after owner claim. Collection needs valid source configuration and is independent of candidate, model and notification readiness. The supervisor checks for newly ready collection roles while running; claiming a preconfigured installation needs no restart. Workers freeze a profile/settings snapshot for each task and read the latest revision before the next task. Stale model results cannot publish downstream work after the profile revision changes. Matching, résumé generation and delivery remain inactive in the browser application until their supported task integrations are complete. Saving model credentials is not proof that they work; the separate capability test is explicit. Fresh setup makes no model calls or external notifications.

The browser offers account access, stored jobs, Profile and Job Filters with explicit Save, revision labels and conflict detection, and independent AI Model connection forms. Unknown fields remain unknown; only confirmed facts enter candidate evidence. Saved filters do not yet apply Jev decisions to the job board. Search-run controls and document imports remain later tasks.

## Dot relay

Set `dot_outbox_path: data/dot-outbox`. An atomic JSON file per stable notification key contains title, body, timestamp and optional PDF path; repeated local delivery writes the same key once. The delivery row records acceptance into this outbox, not receipt by the user.

A separately configured Codex thread heartbeat reads new events, reports openings and draft warnings, links PDFs and updates the user-authorized Apply To Google Sheets tab. It preserves manual application status, dates and notes, matches existing employer URLs/requisitions before adding rows, and records separate sheet-write and notification checkpoints in `data/dot-relay-state.json`. It does not alter confirmed Applications or Watchlist tabs. Resume PDF cloud uploads require explicit destination authorization; otherwise PDFs remain local and are linked in Dot messages. It treats job text as untrusted data and restricts attachments to the project's artifacts directory. A five-minute heartbeat was configured for the initial local setup and stays quiet without new events. It needs the host and Codex available; a remote deployment needs an explicit secure relay. Cloning this repository does not create an automation.

Use Apprise directly when latency must avoid the heartbeat interval. Neither route submits applications.

## Inspect, restart, and preserve data

`docker compose logs app` shows startup and worker exits. `docker compose restart app` reloads operational source/path configuration and preserves the volume. Profile and Job Filters saves require no restart. For a configured worker database, use `docker compose exec app internship-pipeline --config /var/data/config/settings.yaml status` to inspect queue/source state. The existing retry, backup, and collection commands remain available through that executable.

For a complete offline backup, stop the app cleanly and copy the entire named volume with host backup tooling, including `identity.sqlite3`, job storage, configuration, source documents, artifacts/checkpoints, and any credential files. Preserve ownership. The existing CLI database-native backup command covers its configured job database only; it is not a complete account/document backup. Never copy just the main SQLite file while live WAL writes continue, and never mix files from different recovery points. Restore only into a stopped instance and preserve the previous volume separately first.

Local tests exercise account/session persistence and real supervisor/API restart with a synthetic directory. Docker Compose syntax validates, but image build/run and complete volume restore were not verified on this host because its Docker engine did not respond. Portable-image and coordinated-backup acceptance remain later task gates.
