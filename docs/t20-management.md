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

`--install-dir /private/installation` before the subcommand selects an existing installation explicitly. `show-url` is an alias for `url`. URL discovery works with the runtime stopped; `open` invokes the system browser only when explicitly requested. The URL is the saved loopback origin, never a guessed wildcard address or token-bearing link.

| Command | Behavior and limits |
| --- | --- |
| `start` | Inspects ownership and starts only the existing saved container. Already-running containers are retained. Waits for the image healthcheck, which uses `/readyz`; accepts a 1–120 second readiness deadline. It never pulls, creates, replaces, or resets installation resources. |
| `stop` | Stops only the owned saved container with a bounded graceful shutdown, verifies it stopped, and retains the named volume. An already-stopped container is retained. |
| `status` | Shows runtime, container running state, image readiness and URL. This unauthenticated lifecycle view contains no owner work data. Readiness is the image healthcheck result; it can lag an application change by the healthcheck interval. |
| `logs` | Captures a bounded runtime tail of 1–200 lines and prints recognized worker-exit/start-failure events plus a count of omitted lines. Unknown lines, exception text, setup tokens and credentials are omitted. It is a sanitized summary rather than a raw engine-log pass-through. |
| `status --diagnostics` | Prompts for the owner username/password in an interactive terminal, then shows bounded source freshness, queue/activity, worker health, failed-work and model-status summaries from the authenticated application API. |
| `logs --diagnostics` | Uses the same explicit owner login and prints the application's sanitized work-failure event view. |
| `setup-token` / `recover-owner` | Require a stopped owned application container and private interactive terminal. Pin maintenance to the inspected container image ID, saved endpoint and preserved volume, with networking and image pulls disabled. They leave the application stopped, and the exclusive installation lock still rejects any separately running writers. |

The schema-1 `installation.json` records the installation UUID, explicit image version/digest, engine executable, captured local endpoint (and Podman SSH identity where needed), container/volume names, port and origin. The shared runtime helper validates its owner and write permissions and refuses incompatible resource labels, image, data mount or loopback port mapping. Commands use literal argument vectors and the saved endpoint; inherited Docker/Podman connection variables cannot redirect them. They never change a global engine context or start runtime software. Missing runtime, manifest, container or volume produces an actionable failure. Missing data is never treated as permission to create a second installation.

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

Prepared Docker syntax for step 2 is shown below. Replace the quoted placeholders with the saved manifest's values and a new owner-only host backup directory. These are documentation examples; actual engine execution is unverified.

```sh
docker --host 'unix:///saved/local/docker.sock' run --rm --network none \
  --entrypoint internship-pipeline \
  --mount 'type=volume,src=SAVED_VOLUME,dst=/var/data' \
  --mount 'type=bind,src=/private/new-backup-parent,dst=/backups' \
  'SAVED_IMAGE_VERSION_OR_DIGEST' backup /backups/snapshot --data-dir /var/data
```

The non-root image user must be able to write the private backup mount; provision suitable local permissions without making the backup public. For Podman, use the manifest's saved executable and `--url`/`--identity` values, or `--remote=false` for native local operation. Do not use a new global connection or silently switch engines. SELinux mount permissions and cross-runtime volume behavior have not passed actual acceptance.

The existing T18 recovery runner restores to `/var/data/restored` inside a separate volume and starts with `PIPELINE_DATA_DIR=/var/data/restored`. That is the prepared container recovery pattern, not verified image evidence. The T19 installer currently provisions the default `/var/data` root and does not register restored subdirectory roots; automatic restore registration remains unavailable. Follow T17's explicit destination-host configuration and retain the original installation rather than claiming an installer rerun adopts a restore automatically. Local `recover-owner` prompts for credentials and revokes sessions under the offline lock; no public owner-recovery bypass exists.

## Explicit image changes

There is no automatic updater. Installer reruns retain the saved image, endpoint, port and data. Before changing an image, record the original digest and keep a complete same-version private backup, then stop the installation. Inspect the candidate release's documented database-version contract and validate a separate fresh restore with that exact image before switching any installation manifest/container. T18 currently verifies neither cross-release migration nor downgrade compatibility, so upgrading existing data is not approved by this preparation. Running an older image against data already opened by a newer image is unsupported; recovery uses the old image and its full pre-change backup in a fresh destination. Never edit only the manifest's image while leaving a mismatched container, and never reset the original volume to make an update succeed.

## Recorded checks and missing acceptance

`PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_management.py` passes **46 tests**. Temporary executable fixtures simulate Docker and Podman command contracts: literal argv with spaces/shell metacharacters, frozen endpoint/connection environment, idempotent start/stop, matching UUID labels/image/mount/port, missing installation/volume/container, engine errors, readiness/call timeouts, bounded limits, safe logs and symlinked launcher imports. One test exercises the management client's request serialization against the real native application API through a FastAPI TestClient-backed opener with synthetic owner/work data, checking authenticated diagnostics, Origin/CSRF login, sanitized failures, logout and session cleanup. Redirect/error handling, malformed session refusal before password submission, noninteractive credential refusal, refusal of an echoing password prompt and explicitly requested browser-opening behavior also pass; browser opening is mocked. Owned Ruff and management-module mypy pass. These fixtures do not establish that either actual engine accepts the prepared argv or that an image serves the HTTP client end to end.

T20 still requires T18's actual image/architecture/runtime acceptance and T19's real saved installation, then installed-command start/stop/status/logs/URL, authenticated diagnostics over the serving container, persistent-data checks across lifecycle actions, stopped/missing-runtime recovery, and same-image backup/fresh restore on each declared runtime. The public installer URL, published release image, supported matrix and resource measurements remain undecided or unverified upstream. No actual image pull, engine action, provider request, publication, reset, prune or disk cleanup was performed in this slice.
