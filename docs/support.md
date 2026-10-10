# Support, troubleshooting and recovery

This checkout has passing native/synthetic acceptance and incomplete image/platform/provider acceptance. No production OS/runtime/browser support promise exists yet. Start with the [release matrix](release-readiness.md) to identify whether a failure crosses a verified boundary or one still awaiting evidence.

## Diagnose a running installation

Open authenticated Settings → Diagnostics and record the sanitized failure code, affected task/run, source freshness and worker heartbeat. A missing connection is incomplete configuration; a failed test or stalled worker is a service failure. Correct the corresponding Models, Profile, Sources, Resume Generation or Notifications & Integrations settings and review the new saved revision before retrying work.

For a native installation, the maintenance CLI exposes `status`, `jobs`, `retry` and `--help`; pass the installation's `--config` before the subcommand and select the same `PIPELINE_DATA_DIR` for identity/key operations. A command targeting default paths instead of the existing instance can inspect a different database, so confirm effective paths first. The [prepared host management command](t20-management.md) is a separate runtime wrapper even though it shares the `internship-pipeline` name with the in-container Python maintenance CLI. It provides `start`, `stop`, `status`, `logs`, `url` and explicit `open` against the saved installation; `status --diagnostics` or `logs --diagnostics` requests an interactive owner login. It preserves the volume and never installs a replacement when data is missing.

After a [local install](t19-installer.md), the browser opens account setup with only username and password. If needed, run `internship-pipeline open` on the host for a fresh private setup link. Keep that link private and use ordinary sign-in after the instance is claimed. Owner password recovery still requires a stopped installation; do not run `recover-owner` against a running service.

## Common failures

| Symptom | Action and limit |
| --- | --- |
| Browser cannot open or readiness fails | Confirm the configured loopback port/origin and whether the service/runtime is running. Container syntax checks do not establish a healthy engine or runnable image. Resolve runtime availability before reinstalling; preserve the current volume. |
| Setup link is rejected | Run `internship-pipeline open` for a fresh private link while unclaimed. A first-run link is single-use. Sign in if the installation is already owned; recover a lost password locally using the maintenance console below. Do not create another instance to bypass account ownership. |
| Model is unconfigured or test fails | Save/test the current official endpoint/model revision in AI Models. Authentication, rate limit, unsupported output/model, timeout and malformed output are distinct errors. Missing credentials are a blocker, and a passed capability probe does not certify matching quality. |
| No jobs or source fails | Inspect enabled sources, saved search revision, due times and freshness. Initial board inventory is backlog; remote ATS/JobSpy throttling or malformed responses can postpone useful results. Correct a source in Settings, then return to the setup/run preview. |
| Matching or a draft is stale | Profile/model/job changes invalidate fingerprints. Inspect the current revision and supported facts; retry the intended current task rather than treating an old PDF as current. Automatic generation stays off unless explicitly enabled. |
| PDF import/render fails | Imports support bounded text-bearing PDF/DOCX; encrypted/image-only files and unsupported template characters have explicit limits. Native PDF rendering needs `pdflatex` and template packages. Actual image TeX/resources are still unverified. |
| Email is uncertain | SMTP acceptance is not receipt. Check the delivery ledger and mailbox privately; deliberate retry after ambiguous acceptance may duplicate a remote message. Do not automatically replay uncertain sends. |
| Sheets sync stops | Review credentials/share permission, current mapping, stable IDs, formulas, grid bounds and changed-cell conflicts; prepare a fresh preview after correcting them. Keep manual notes/formulas outside owned columns and avoid concurrent manual edits to owned cells during sync. |
| Credential key is missing/wrong | Stop writers and restore the exact key/database pair from a complete private backup. Do not generate a replacement key over stored credentials; use replacement provider credentials if the original cannot be recovered. |
| Runtime reports no space | Preserve installation/backup data and resolve host/runtime capacity through the operator's normal process. Disk reset/prune/delete is outside these docs. The last Colima image attempt paused on `nospace`; it provides no image acceptance result. |

## Full backup and fresh restore

Stop the application and every worker before backup; the supported entry points hold installation locks while active. A full backup includes both SQLite databases, exact credential key, effective config, source registries, source provenance and all artifact/document bytes. The manifest verifies sizes/hashes and key decryption. Do not copy only the jobs database or copy live SQLite files as a full recovery method.

The **Python maintenance CLI** accepts:

```sh
internship-pipeline backup /private/backups/pipeline-snapshot --data-dir /private/pipeline
internship-pipeline restore /private/backups/pipeline-snapshot /private/pipeline-restored
internship-pipeline recover-owner --data-dir /private/pipeline-restored
```

These paths are placeholders; backup output and restore destination must be new. In a native synced repo use `uv run --frozen internship-pipeline` for this CLI. In the proposed container it runs inside a stopped-installation one-off image container with the data and backup mounts; use the [explicit T20 recipe](t20-management.md#private-backup-and-recovery) once real container acceptance is available. The host management wrapper is not an alias for these maintenance subcommands.

Fresh restore validates the entire manifest and credentials, retains confirmed email/Sheets checkpoints and explicit application state, revokes sessions and marks interrupted side effects for review. Select the restored host's origin/service settings, start it, sign in and inspect jobs/documents before retiring the original. Restore currently guarantees a same-version installation contract; no upgrade migration/downgrade support has been established.

`recover-owner` prompts privately for username and a new password twice and revokes all sessions; it requires local access to the instance. It does not create a public recovery endpoint. Existing owner identity closes first-run claim permanently. See [T17](t17-operations.md) for native evidence and [T18](t18-portable-images.md) for the separate pending actual-image interruption/restore checks.

## Issue and security reports

Share source/image version, host OS/architecture, runtime, configured local port, sanitized status/error code, exact failing step and a synthetic reproduction. State whether provider responses were synthetic or live. Keep credentials, setup tokens, cookies, private candidate facts and raw provider responses out of issue text/screenshots. Raw service logs may contain the setup token, so inspect them privately and share only manually redacted excerpts.

A published private security contact and supported-version policy remain release requirements; none is configured in this checkout. Establish that route before public distribution. Report ordinary reproducible behavior through the repository's issue mechanism when available, and keep exploitable details/private data out of public reports until a private route exists. Current limitations and missing acceptance are tracked in [release readiness](release-readiness.md).
