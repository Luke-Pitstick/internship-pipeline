# Support, troubleshooting and recovery

Start with the installed version, runtime status and the failure shown in Settings → Diagnostics. Include those details when reporting a problem.

## Diagnose a running installation

Open authenticated Settings → Diagnostics and record the sanitized failure code, affected task/run, source freshness and worker heartbeat. A missing connection is incomplete configuration; a failed test or stalled worker is a service failure. Correct the corresponding Models, Profile, Sources, Resume Generation or Notifications & Integrations settings and review the new saved revision before retrying work.

For a native installation, the maintenance CLI exposes `status`, `jobs`, `retry` and `--help`; pass the installation's `--config` before the subcommand and select the same `PIPELINE_DATA_DIR` for identity/key operations. A command targeting default paths instead of the existing instance can inspect a different database, so confirm effective paths first. The host management command is a separate runtime wrapper even though it shares the `internship-pipeline` name with the in-container Python maintenance CLI. It provides `start`, `stop`, `status`, `logs`, `url` and explicit `open` against the saved installation; `status --diagnostics` or `logs --diagnostics` requests an interactive owner login. It preserves the volume and never installs a replacement when data is missing.

After a [local install](../README.md#installation), the browser opens account setup with only username and password. If needed, run `internship-pipeline open` on the host for a fresh private setup link. Keep that link private and use ordinary sign-in after the instance is claimed. Owner password recovery still requires a stopped installation; do not run `recover-owner` against a running service.

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
| Runtime reports no space | Preserve installation/backup data and resolve host/runtime capacity through the operator's normal process. Disk reset/prune/delete is outside these docs. |

## Full backup and fresh restore

Stop the application and every worker before backup; the supported entry points hold installation locks while active. A full backup includes both SQLite databases, exact credential key, effective config, source registries, source provenance and all artifact/document bytes. The manifest verifies sizes/hashes and key decryption. Do not copy only the jobs database or copy live SQLite files as a full recovery method.

The **Python maintenance CLI** accepts:

```sh
internship-pipeline backup /private/backups/pipeline-snapshot --data-dir /private/pipeline
internship-pipeline restore /private/backups/pipeline-snapshot /private/pipeline-restored
internship-pipeline recover-owner --data-dir /private/pipeline-restored
```

These paths are placeholders; backup output and restore destination must be new. In a native synced repo use `uv run --frozen internship-pipeline` for this CLI. In the proposed container it runs inside a stopped-installation one-off image container with the data and backup mounts; use the container backup and recovery procedure below. The host management wrapper is not an alias for these maintenance subcommands.

Fresh restore validates the entire manifest and credentials, retains confirmed email/Sheets checkpoints and explicit application state, revokes sessions and marks interrupted side effects for review. Select the restored host's origin/service settings, start it, sign in and inspect jobs/documents before retiring the original. Restore currently guarantees a same-version installation contract; no upgrade migration/downgrade support has been established.

`recover-owner` prompts privately for username and a new password twice and revokes all sessions; it requires local access to the instance. It does not create a public recovery endpoint. Existing owner identity closes first-run claim permanently.

### Container installations

For a stopped Docker installation, this backup procedure uses a separate owned backup volume, then streams its archive to the host. This avoids binding a host-UID-owned mode-0700 directory into the UID-10001 image. Replace placeholders with the saved endpoint, source UUID/volume/container, exact inspected local image ID, recorded data root and a newly generated backup-volume name. Preserve both volumes. These commands remain actual-engine acceptance cases.

```sh
docker --host 'SAVED_UNIX_ENDPOINT' volume create \
  --label 'io.internship-pipeline.install-id=SAVED_SOURCE_UUID' 'NEW_BACKUP_VOLUME'
docker --host 'SAVED_UNIX_ENDPOINT' run --rm --pull never --network none \
  --read-only --tmpfs /tmp --entrypoint python \
  --mount 'type=volume,src=NEW_BACKUP_VOLUME,dst=/var/data' \
  'SAVED_LOCAL_IMAGE_ID' -c \
  "from pathlib import Path; Path('/var/data/backup').mkdir(mode=0o700)"
docker --host 'SAVED_UNIX_ENDPOINT' run --rm --pull never --network none \
  --read-only --tmpfs /tmp --entrypoint internship-pipeline \
  --mount 'type=volume,src=SAVED_SOURCE_VOLUME,dst=/var/data' \
  --mount 'type=volume,src=NEW_BACKUP_VOLUME,dst=/recovery' \
  'SAVED_LOCAL_IMAGE_ID' backup /recovery/backup/snapshot --data-dir 'SAVED_DATA_DIR'
umask 077
set -C
docker --host 'SAVED_UNIX_ENDPOINT' run --rm --pull never --network none \
  --read-only --tmpfs /tmp --entrypoint python \
  --mount 'type=volume,src=NEW_BACKUP_VOLUME,dst=/var/data,readonly' \
  'SAVED_LOCAL_IMAGE_ID' -c \
  "import sys, tarfile; archive = tarfile.open(fileobj=sys.stdout.buffer, mode='w|'); archive.add('/var/data/backup/snapshot', arcname='snapshot'); archive.close()" \
  > /private/backups/new-snapshot.tar
```

Create the host backup parent privately first; `set -C` prevents replacing an existing archive and `umask 077` keeps the output owner-only. The initial one-off volume mount at the image's owned `/var/data` initializes ordinary Docker/Podman volume copy-up ownership for its UID 10001. Mounting that same volume at `/recovery` preserves the ownership; no host backup permissions, user namespaces or source bytes are changed. Verify this behavior on each declared runtime before claiming it works. A failed command retains the new backup volume and source; don't reuse an incomplete backup or remove a useful volume to retry.

Extract the archive as the host owner into the private parent, refusing links and unsafe paths. The new `snapshot` destination must not already exist:

```sh
python3 - <<'PY_BACKUP'
from pathlib import Path
import os, tarfile
parent = Path('/private/backups')
assert not (parent / 'snapshot').exists()
os.umask(0o077)
def regular(member, destination):
    if not (member.isfile() or member.isdir()):
        raise ValueError('Backup archive accepts only regular files and directories')
    return tarfile.data_filter(member, destination)
with tarfile.open(parent / 'new-snapshot.tar') as archive:
    archive.extractall(parent, filter=regular)
PY_BACKUP
```

The source container's `Image` field supplies `SAVED_LOCAL_IMAGE_ID`; this local content identity is distinct from the registry digest. Use the manifest's `data_dir` so recovered installations back up their restored root. For Podman, use the manifest's saved executable and `--url`/`--identity`, or `--remote=false` for native local mode. Keep the generated backup volume's source UUID label and inspection evidence. The private host archive plus extracted directory are secret recovery material; retain an encrypted offline copy. No raw tokens/credentials are printed by the host-installed lifecycle command.

The explicit installer recovery path manages the same `/var/data/restored` root used by the container smoke runner. With the complete reviewed bundle and a new destination, run:

```sh
sh /private/reviewed-bundle/install.sh \
  --restore-from /private/backups/snapshot \
  --restore-source /private/original-installation \
  --install-dir /private/recovered-installation \
  --command-dir /private/recovered-commands --port 18080
/private/recovered-commands/internship-pipeline status
/private/recovered-commands/internship-pipeline status --diagnostics
```

Paths are placeholders; the hosted equivalent must use the exact verified installer bundle. The source must still have its owned stopped container and retained volume; the new port must differ. No new runtime or image is selected. Restore reads the owner-only host backup as the invoking host user, creates a private temporary tar, and passes it through stdin to the source image with pulls/network disabled and only a new labelled destination volume mounted. The non-root image user extracts regular files/directories privately into `/var/data/backup`, checks the transferred manifest SHA-256, then restores into `/var/data/restored`. The host backup is never mounted, chmodded or chowned; source UID and rootless namespace mappings cannot make its mode-0700 path unreadable to this transfer. The backup/restore service validates both databases, encryption key and retained documents and writes fresh configuration at `/var/data/restored/config/settings.yaml`. Owner passwords survive and sessions are revoked. Verify jobs, readable PDFs, decrypted connections and retained confirmed side-effect ledgers before keeping only the recovered installation; authorization for live delivery/provider work is separate.

The transfer reserves temporary host disk for the private tar, and the fresh volume retains both the transferred backup and restored data. Plan host temporary space of at least the backup size plus tar overhead and volume capacity for both copies; measure actual disk requirements on the target host. A total 600-second deadline covers archive creation checks, subprocess stdin transfer and restore; a stopped receiver times out instead of blocking an unbounded pipe write. Only the installer's unlinked temporary file is cleaned automatically. `.backup-manifest.sha256` records the copied backup identity before `.restore-completed` permits app startup. Image UID ownership, fresh-volume copy-up permissions and real Docker/Podman stdio remain actual-runtime gates, covered separately from native archive regressions.

The destination command uses its own manifest and completion marker, so `start`, `stop`, diagnostics and offline `recover-owner` work after the checkout and original command path are unavailable. Recovery never adopts the original volume. A successful restore followed by a failed container create/start can resume with the same bundle and destination paths, without restore flags or another pull. An unconfirmed restore cannot start through either installer or management; preserve its volume and use a different fresh destination for another attempt. Do not delete markers, edit only the manifest, or overwrite an existing restored directory to force progress.

## Issue and security reports

Share source/image version, host OS/architecture, runtime, configured local port, sanitized status/error code, exact failing step and a synthetic reproduction. State whether provider responses were synthetic or live. Keep credentials, setup tokens, cookies, private candidate facts and raw provider responses out of issue text/screenshots. Raw service logs may contain the setup token, so inspect them privately and share only manually redacted excerpts.

A published private security contact and supported-version policy remain release requirements; none is configured in this checkout. Establish that route before public distribution. Report ordinary reproducible behavior through the repository's issue mechanism when available, and keep exploitable details/private data out of public reports until a private route exists.
