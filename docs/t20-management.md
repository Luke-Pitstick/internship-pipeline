# T20 — Existing-installation management preparation

October 7, 2026. **Partial: management implementation and synthetic/native checks pass; installed-image acceptance is unverified.** T18 has no verified published image, platform/runtime matrix or successful local application-container run. T19's hosted installation acceptance is consequently open. The stopped Colima VM's disk `nospace` error is unchanged; these checks never start it or contact an actual engine.

## Commands and saved installation

The host management entrypoint is `deploy/internship-pipeline`. T19 copies that file, `pipeline_management.py` and the shared `pipeline_runtime.py` into the private installation's `command/` directory, then links the executable into the chosen command directory. The default installation directory is `~/.local/share/internship-pipeline`; a copied command resolves its own installation directory, including when a custom directory was selected. No repository checkout or Python application dependencies are needed by the copied command; it does require Python 3.12 or newer. This is a candidate command, not an advertised hosted release.

```sh
internship-pipeline --help
internship-pipeline status
internship-pipeline start --wait 60
internship-pipeline stop
internship-pipeline logs --lines 100
internship-pipeline status --diagnostics
internship-pipeline logs --diagnostics
internship-pipeline stop
internship-pipeline setup-token
# For a claimed instance: internship-pipeline recover-owner
internship-pipeline start
internship-pipeline url
internship-pipeline open
```

`--install-dir /private/installation` before the subcommand selects an existing installation explicitly. `show-url` is an alias for `url`. URL discovery works with the runtime stopped; `open` invokes the system browser only when explicitly requested. `url` prints the saved loopback origin without contacting the engine. `open` requires the owned container to be running and ready; it issues and opens a private setup link before claim, or opens ordinary sign-in after claim. Keep its output private.

| Command | Behavior and limits |
| --- | --- |
| `start` | Inspects ownership and starts only the existing saved container. Already-running containers are retained. Waits for the image healthcheck, which uses `/readyz`; accepts a 1–120 second readiness deadline. It never pulls, creates, replaces, or resets installation resources. |
| `stop` | Stops only the owned saved container with a bounded graceful shutdown, verifies it stopped, and retains the named volume. An already-stopped container is retained. |
| `status` | Shows runtime, container running state, image readiness and URL. This unauthenticated lifecycle view contains no owner work data. Readiness is the image healthcheck result; it can lag an application change by the healthcheck interval. |
| `logs` | Captures a bounded runtime tail of 1–200 lines and prints recognized worker-exit/start-failure events plus a count of omitted lines. Unknown lines, exception text, setup tokens and credentials are omitted. It is a sanitized summary rather than a raw engine-log pass-through. |
| `status --diagnostics` | Prompts for the owner username/password in an interactive terminal, then shows bounded source freshness, queue/activity, worker health, failed-work and model-status summaries from the authenticated application API. |
| `logs --diagnostics` | Uses the same explicit owner login and prints the application's sanitized work-failure event view. |
| `open` | Opens a private setup link for an unclaimed ready installation, invalidating earlier unclaimed links. After claim it opens ordinary sign-in without changing the owner. |
| `setup-token` / `recover-owner` | Require a stopped owned application container and private interactive terminal. Pin maintenance to the inspected container image ID, saved endpoint and preserved volume, with networking and image pulls disabled. They leave the application stopped, and the exclusive installation lock still rejects any separately running writers. |

The schema-1 `installation.json` records the installation UUID, explicit image version/digest (or exact local image ID for recovery), required data directory, engine executable, captured local endpoint (and Podman SSH identity where needed), container/volume names, port and origin. The shared runtime helper validates its owner and write permissions and refuses incompatible resource labels, image, data mount or loopback port mapping. Commands use literal argument vectors and the saved endpoint; inherited Docker/Podman connection variables cannot redirect them. They never change a global engine context or start runtime software. Missing runtime, manifest, container or volume produces an actionable failure. Missing data is never treated as permission to create a second installation.

Owner diagnostics perform `/api/session` → CSRF-protected `/api/login` → `/api/diagnostics` → `/api/logout`. Cookies remain in process memory, redirects and ambient HTTP proxies are disabled, responses have a size limit, and individual requests have a five-second timeout. The client clears its cookie jar even on error and attempts logout after a session exists; a network failure during logout may leave that short-lived server session until normal expiry. Passwords/tokens aren't accepted as arguments or saved in files. Output includes an additional field/value allowlist, so arbitrary response fields cannot print credentials or private exception text. Diagnostics show the activity available in T17; they do not claim a complete history of completed search runs. Use Settings → Diagnostics to inspect and deliberately retry work.

## Private backup and recovery

The host command manages lifecycle and has explicit stopped-only token/owner recovery
commands. They delegate to the **image's** maintenance CLI using the saved installation
contract. In a private terminal, run host `stop`, stop separately launched writers, run
host `setup-token` (unclaimed) or `recover-owner` (claimed), then run host `start` only
after success and verify sign-in. The maintenance CLI also supports `backup` and `restore`;
use `--entrypoint` to invoke those instead of the normal application entrypoint. Read
the complete [T17 stopped-instance backup and recovery contract](t17-operations.md).
Both databases, the exact encryption key, retained upload provenance/files,
configuration and artifacts are required. Copying a subset is insufficient.

1. **Stop supported writers.** Run the host `stop` command and stop any separately launched workers or maintenance processes. Preserve the existing volume and manifest. T17's exclusive offline installation lock refuses backup/recovery while supported writers remain active.
2. **Create a new private backup.** Use the saved engine endpoint, exact saved image and saved volume. Invoke the image maintenance CLI in a one-off container with networking disabled and a separate owner-only backup mount. The destination must be new; preserve the complete output as secret recovery material, because it contains the key and encrypted connections together.
3. **Restore into a fresh destination.** Use the same image version/digest and restore into a new directory in a separate recovery volume or private directory. Restore refuses an existing destination. Owner passwords survive, browser sessions are revoked, and uncertain delivery work requires review rather than replay.
4. **Verify the fresh application before switching.** Start it with the restored data root, correct origin and a different available loopback port. Check owner login, readiness, retained jobs/documents and connection decryption. Keep the original stopped installation intact until this check passes.

Prepared Docker syntax for step 2 uses a separate owned backup volume, then streams its archive to the host. This avoids binding a host-UID-owned mode-0700 directory into the UID-10001 image. Replace placeholders with the saved endpoint, source UUID/volume/container, exact inspected local image ID, recorded data root and a newly generated backup-volume name. Preserve both volumes. These commands remain actual-engine acceptance cases.

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

The explicit installer recovery path manages the same `/var/data/restored` root used by the T18 runner. With the complete reviewed bundle and a new destination, run:

```sh
sh /private/reviewed-bundle/install.sh \
  --restore-from /private/backups/snapshot \
  --restore-source /private/original-installation \
  --install-dir /private/recovered-installation \
  --command-dir /private/recovered-commands --port 18080
/private/recovered-commands/internship-pipeline status
/private/recovered-commands/internship-pipeline status --diagnostics
```

Paths are placeholders; the hosted equivalent must use the exact verified S4 bundle, as recorded in [installation acceptance](release/installation-acceptance.md). The source must still have its owned stopped container and retained volume; the new port must differ. No new runtime or image is selected. Restore reads the owner-only host backup as the invoking host user, creates a private temporary tar, and passes it through stdin to the source image with pulls/network disabled and only a new labelled destination volume mounted. The non-root image user extracts regular files/directories privately into `/var/data/backup`, checks the transferred manifest SHA-256, then restores into `/var/data/restored`. The host backup is never mounted, chmodded or chowned; source UID and rootless namespace mappings cannot make its mode-0700 path unreadable to this transfer. T17 validates both databases, encryption key and retained documents and writes fresh configuration at `/var/data/restored/config/settings.yaml`. Owner passwords survive and sessions are revoked. Verify jobs, readable PDFs, decrypted connections and retained confirmed side-effect ledgers before keeping only the recovered installation; authorization for live delivery/provider work is separate.

The transfer reserves temporary host disk for the private tar, and the fresh volume retains both the transferred backup and restored data. Plan host temporary space of at least the backup size plus tar overhead and volume capacity for both copies; measure actual disk requirements in S3/S5. A total 600-second deadline covers archive creation checks, subprocess stdin transfer and restore; a stopped receiver times out instead of blocking an unbounded pipe write. Only the installer's unlinked temporary file is cleaned automatically. `.backup-manifest.sha256` records the copied backup identity before `.restore-completed` permits app startup. Image UID ownership, fresh-volume copy-up permissions and real Docker/Podman stdio remain actual-runtime gates, covered separately from native archive regressions.

The destination command uses its own manifest and completion marker, so `start`, `stop`, diagnostics and offline `recover-owner` work after the checkout and original command path are unavailable. Recovery never adopts the original volume. A successful restore followed by a failed container create/start can resume with the same bundle and destination paths, without restore flags or another pull. An unconfirmed restore cannot start through either installer or management; preserve its volume and use a different fresh destination for another attempt. Do not delete markers, edit only the manifest, or overwrite an existing restored directory to force progress.

## First-release image contract

There is no automatic updater, cross-release migration or downgrade compatibility. Installer reruns retain their saved image, endpoint, port and data root. Fresh first-release installation and complete exact-image backup/recovery are the current contract. Upgrading development snapshots by changing their manifest or running a new image against old data is unsupported. Broader updates require a separate requirement and accepted test path; no cross-version procedure is implied by these recovery commands.

## Recorded checks and missing acceptance

The historical October 7 management-only run passed **46 tests**. The October 8 installer/management/native T17 recovery follow-up passes **150 tests, with 1 skipped**, in 54.79 seconds; see [T19](t19-installer.md) for the exact command. New cases verify restored-root lifecycle/owner recovery, completion-marker refusal, config/data-root mismatch and nested-mount refusal. Temporary executable fixtures simulate Docker and Podman command contracts: literal argv with spaces/shell metacharacters, frozen endpoint/connection environment, idempotent start/stop, matching UUID labels/image/mount/port, missing installation/volume/container, engine errors, readiness/call timeouts, bounded limits, safe logs and symlinked launcher imports. One test exercises the management client's request serialization against the real native application API through a FastAPI TestClient-backed opener with synthetic owner/work data, checking authenticated diagnostics, Origin/CSRF login, sanitized failures, logout and session cleanup. Redirect/error handling, malformed session refusal before password submission, noninteractive credential refusal, refusal of an echoing password prompt and explicitly requested browser-opening behavior also pass; browser opening is mocked. Owned Ruff and management-module mypy pass. These fixtures do not establish that either actual engine accepts the prepared argv or that an image serves the HTTP client end to end.

T20 still requires T18's actual image/architecture/runtime acceptance and T19's real saved installation, then installed-command start/stop/status/logs/URL, authenticated diagnostics over the serving container, persistent-data checks across lifecycle actions, stopped/missing-runtime recovery, and same-image backup/fresh restore on each declared runtime. The public installer URL, published release image, supported matrix and resource measurements remain undecided or unverified upstream. No actual image pull, engine action, provider request, publication, reset, prune or disk cleanup was performed in this slice.
