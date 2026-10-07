# Deployment and recovery

Run one application container on a host with local persistent storage for SQLite. The image contains the static Svelte frontend, FastAPI API, Python worker roles, and current résumé tooling. It exposes one port and uses one named volume. Node is used only in the frontend build stage; the runtime uses Python and the bounded application-owned TeX compiler, with no Codex subscription dependency. Actual Docker image acceptance remains unverified while the host is unresponsive.

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

Owner claim activates the independent saved-search, email-delivery and Sheets workers; each processes only its explicitly configured, queued work. Valid operational source configuration additionally enables collection/discovery. A confirmed profile enables master/tailored résumé workers, and a tested current Jev connection enables matching. The supervisor detects newly ready roles while running, so saving setup needs no restart. Collection remains independent of candidate, model and notification readiness. Workers freeze a profile/settings snapshot for each task and read the latest revision before the next task; stale model results cannot publish downstream work after a profile change. Saving credentials does not test them or send notifications. Fresh setup makes no model calls or external notifications.

The browser offers account access, stored jobs, Profile and Job Filters with explicit Save, revision labels and conflict detection, and independent AI Model connection forms. Unknown fields remain unknown; only confirmed facts enter candidate evidence. Saved filters do not yet apply Jev decisions to the job board. Search-run controls and document imports remain later tasks.

## Optional email and Google Sheets

Configure SMTP email under Settings → Notifications & Integrations. The server saves the password encrypted with `model-credentials.key`; alerts and daily digests use an independent durable worker. Saving does not send mail. The explicit test queues a synthetic message to the saved recipient. Optional current PDFs may be attached, but email works before any résumé exists. SMTP uncertainty is displayed for owner review because retrying an ambiguous acknowledgement can duplicate an email. See [T14 setup and evidence](t14-email-alerts.md).

The same panel configures Google Sheets using a dedicated Google Cloud service-account JSON key and one spreadsheet shared with that service-account email as Editor. Enable the Sheets API, paste the key, save the spreadsheet ID, test access to list tabs, choose a tab, and save/test its current revision. Preview outward column mappings before queueing the sync. Only explicitly mapped application status and notes may propose inward changes, which always require owner review. The independent server worker uses stable job IDs, per-row checkpoints, RAW data writes and formula detection; CSV export works when Google is skipped. See the [authorization, ownership and retry contract](t15-spreadsheet-sync.md). The old SSH download script and local Codex spreadsheet relay are removed from this workflow.

The encrypted credentials, delivery/digest membership, sheet journals and review history live in the same jobs database. Preserve the exact existing key with its database and account/document data in a coordinated backup. No integration submits applications; an accepted inward Applied proposal records an explicit owner decision.

## Inspect, restart, and preserve data

`docker compose logs app` shows startup and worker exits. `docker compose restart app` reloads operational source/path configuration and preserves the volume. Profile and Job Filters saves require no restart. For a configured worker database, use `docker compose exec app internship-pipeline --config /var/data/config/settings.yaml status` to inspect queue/source state. The existing retry, backup, and collection commands remain available through that executable.

For a coordinated complete backup, stop the app and every worker, then use the [T17 backup/restore commands](t17-operations.md) with the installation's data directory. The command acquires an exclusive installation lock, snapshots both SQLite databases through their backup APIs, and saves effective configuration, retained upload evidence/files, artifacts and the exact encryption key in one private manifest-verified directory. It refuses an existing output. Do not copy just the main SQLite file while live WAL writes continue or mix recovery points.

Restore verifies database integrity, hashes and credential decryption and creates only a fresh destination; existing installations are never overwritten. Confirmed deliveries and completed Sheets checkpoints remain completed, while interrupted side effects require owner review or a new preview. Sessions are revoked so the restored host requires fresh sign-in. Keep the previous installation separately until restored data and documents are verified. See [operations evidence and exact limitations](t17-operations.md).

Local native tests exercise owner/session persistence, independent worker/API restart and full stopped-directory backup/restore using synthetic inputs. Docker Compose syntax validates, but actual image build/run remains unverified on this host because its Docker engine does not respond. Native restore evidence does not replace actual container/portable-image acceptance.
