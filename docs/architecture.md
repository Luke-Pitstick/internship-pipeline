# Architecture

Internship Pipeline is a single-owner application with a static SvelteKit browser interface, a same-origin FastAPI API, SQLite persistence and ordinary Python worker modules. The proposed container includes the built frontend, Python application and TeX renderer; it uses one persistent `/var/data` volume. Actual image/platform acceptance remains open in [T18](t18-portable-images.md).

```text
Browser → owner session + CSRF → FastAPI → SQLite revisions / durable tasks
                                             ↑
ATS / JobSpy → collector → observations → matcher → persisted Jev assessment
                                             ├→ master / tailored documents
                                             ├→ email membership / delivery
                                             └→ Sheets preview / journal / sync
Owner submits an application → explicit local Applied record
```

## Process and data boundaries

`bootstrap.py` establishes runtime paths and the owner setup state, then `supervisor.py` starts the web process and independently eligible worker roles. New installations serve account/setup screens before a profile or provider exists. The supervisor refreshes configured roles as setup progresses; missing inputs disable their dependent roles. Collection, matching, master/tailored rendering, saved-search runs, email, Sheets and discovery have separate processes and durable queue state. Delivery and model failures can degrade their own roles while collected observations remain usable.

`storage.py` and `queue.py` own persistent job/task state. `identity.py` owns a separate identity database, hashed passwords, one-time owner claim and sessions. `profile_settings.py`, `model_connections.py` and their routers save immutable revisions with optimistic edit checks; settings are read at task boundaries. Jobs preserve source publication/closure evidence separately from first observation, assessment and delivery timestamps.

`collection.py` and `sources/` normalize independent ATS/JobSpy inputs. Only audited complete direct-board snapshots can close jobs, after two complete misses; partial responses add observations without closing jobs. Initial inventories enter labeled backlog. `search_runs.py` and `run_limits.py` coordinate saved runs, progress, cancellation and resource reservations rather than making collection wait on notifications.

`assessments.py` and `providers/` persist authoritative criterion decisions, evidence IDs, confidence, fit distributions and selected/resolved model identity. Owner overrides remain inspectable. Exact mandatory comparisons require supported normalized facts; unknown/conflicting or model-derived rejection remains in review under the unmet [Jev quality gate](t02-followup.md). Profile/model/job revisions invalidate stale assessments and generation fingerprints.

`profiles/` extracts bounded PDF/DOCX text locally in a separate process and stores reviewed source provenance. `resumes/master_template.py` escapes confirmed facts into an application-owned template; `master.py` renders without inference. `tailored.py` and `tailored_provider.py` ask the general LLM to select confirmed fact IDs, preserve selected wording, validate changes and render asynchronously. The browser reviews differences, preview/download and explicit review state. `generation_policy.py` provides off-by-default bounded automation independent of delivery.

`email_integrations.py` stores SMTP configuration, membership, attempts and acceptance/uncertainty state. `sheets_integration.py` stores explicit column ownership, preview fingerprints, row checkpoints, pre-I/O journals and inward proposals; `sheets_provider.py` implements the supported Google service-account path. Neither integration reruns matching. Accepted SMTP is not guaranteed mailbox receipt, and Google writes cannot exclude concurrent edits inside a remote write interval.

`operations.py` owns stopped-instance locks, manifest-verified full backup, fresh-only restore, side-effect interruption handling and local owner recovery. Restore preserves confirmed work, revokes browser sessions and leaves uncertain external effects for review. [Operations](t17-operations.md) gives the exact retained data and limits.

## Persistence and deployment

The default instance contains `state.sqlite3`, `identity.sqlite3`, the exact `model-credentials.key`, configuration/registries and private artifact/provenance files. Explicit operational settings can select a different jobs database name; backup uses those effective paths. Secrets are Fernet-encrypted with the instance key, so the complete volume and full backups remain private recovery material. There is no multi-user or distributed-database deployment contract.

Compose binds a local loopback port, runs the image as UID 10001 with a read-only root, supplies `/tmp` tmpfs and preserves the named data volume across stop/start. HTTP origins must be loopback; remote deployment requires a deliberately configured HTTPS origin and operator-managed TLS. The app disables forwarded-proxy trust by default. These are configured boundaries, not a completed security audit or certified remote-host deployment.

The Python and npm lockfiles define dependency inputs; frontend build uses Node.js 22 and runtime uses Python 3.12 Bookworm. Candidate image CI prepares native amd64/arm64 Docker and rootless Podman checks, OCI export, provenance and SBOM, but has no registry publishing step or passing platform report yet. [Host installer](t19-installer.md)/[management preparation](t20-management.md) uses a saved explicit image/runtime endpoint and owned container/volume identity under the [saved manifest contract](installation-manifest.md); it cannot substitute for real image acceptance. See [release readiness](release-readiness.md), [privacy](privacy.md) and [contributing](../CONTRIBUTING.md).
