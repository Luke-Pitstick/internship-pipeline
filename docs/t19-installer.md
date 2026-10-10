# T19 — Installer and hosted launcher

October 8 hosted-launcher follow-up: the [curl publication workflow](release/curl-publication.md) generates a release-specific `install.sh` that supplies the verified bootstrap/bundle hashes and GHCR digest automatically. Users do not clone the checkout or enter an image reference. This generated release asset is different from the local `deploy/install.sh` below, which expects adjacent bundle files. [End-to-end acceptance](release/curl-installation-acceptance.md) records the current verification scope; anonymous publication and real hosted installation remain separate gates.

October 7, 2026. **Partial implementation; hosted installation and actual runtime acceptance remain blocked on T18.** There is no verified published image, installer URL or certified OS/architecture/runtime matrix. The stopped Colima VM's `nospace` condition was left unchanged. This work uses executable fake runtimes and does not pull an image or operate any actual engine.

## Local entrypoint

From a complete reviewed checkout, `sh deploy/install.sh --help` shows the installer without contacting a runtime. The shell launcher checks for Python 3.12 or newer and the full local bundle. A concrete local installation command, once a verified image exists, is:

```sh
sh deploy/install.sh --image 'REGISTRY/IMAGE:VERSION' --runtime docker --port 8080
```

`REGISTRY/IMAGE:VERSION` is an explicit placeholder, not a published project image. A reviewed sha256 digest can be supplied instead. This local entrypoint requires an explicit image; the generated hosted launcher supplies its release's pinned digest as a first-install default. Existing installations and exact-image restores ignore that default and preserve their saved image. No mutable `latest` image fallback is used. `python3 deploy/install.py` exposes the local options; use Python 3.12 or newer. The installer never silently installs Python, runtime software, privileged services or a VM.

The host management command is provisionally `internship-pipeline`, placed in `~/.local/bin`. The private installation root defaults to `~/.local/share/internship-pipeline`. `--command-dir` and `--install-dir` select other paths; the copied management bundle resolves its own installation path, so the installed command remains usable after the checkout is removed. It includes help/status and the [T20 lifecycle and diagnostic commands](t20-management.md), using only Python's standard library. The image's application-maintenance CLI uses the same name inside the container; host and image commands have different responsibilities.

The installer opens the default browser to a private setup link, where account creation asks only for username and password. On a headless host, open the printed link; `--no-open` deliberately suppresses automatic browser launch. The link carries a single-use secret in its fragment, which is never sent in HTTP requests. The page removes it from browser history immediately, retains it in tab session storage across reloads, and clears it after claim. Keep installer output and private links out of shared transcripts. `internship-pipeline open` can issue a fresh link while an unclaimed installation is running; issuing a new link invalidates previous unclaimed links. An existing owner receives the ordinary sign-in URL and cannot be replaced through this command. Readiness alone never claims the instance. Owner password recovery remains offline.

The selected hosted contract uses GitHub Release `install.sh` assets and the installed `internship-pipeline` command. The [distribution preparation](release/distribution.md) defines the versioned five-deploy-file bundle plus MIT `LICENSE` and Python bootstrap verification contract; the local shell entrypoint deliberately refuses a missing bundle. Public asset/package access, published immutable identities and exact hosted execution remain acceptance gates. See the [installation run sheet](release/installation-acceptance.md) before advertising a live command.

## Fresh exact-image recovery

The reviewed bundle also accepts `--restore-from /private/complete-snapshot --restore-source /private/original-install-root --install-dir /private/new-install-root --command-dir /private/new-command-dir --port 18080`. Both restore flags are required, using their full names; argparse abbreviations are disabled. Stop the original installation and all separately launched writers first, and take its complete T17 backup. Choose a distinct port and new empty root/command directory. The source image may be version-tagged: recovery pins the actual inspected local image ID, uses its saved engine endpoint/SSH identity and performs no pull. Do not supply a different `--image` or `--runtime`.

The new owned volume restores to `/var/data/restored` and the private manifest records that root for the application and installed management. Once restore completion is recorded, ordinary reruns can recreate/start its missing or stopped container without repeating restore. An interrupted/unconfirmed restore keeps its volume and refuses startup; create a separate fresh recovery destination rather than removing markers or modifying the manifest. The original volume/container/root remain untouched. The host owner copies the private backup through a temporary tar and container stdin; no host backup bind, chmod/chown or UID mapping override is used. The image user extracts/validates it in the new owned volume before restore. Temporary host disk, destination space for two copies, fresh-volume image-UID ownership and actual engine stdio need per-host acceptance.

This first release has no automatic updater or data compatibility across development/release snapshots. Install a fresh release or restore that installation's complete backup using its exact image. Do not edit an old manifest into the new schema or claim an installer rerun upgrades it.

## Runtime choice and storage

The candidate host guard accepts Linux/macOS on amd64/arm64 and refuses other combinations. The installer probes installed Docker and Podman CLIs with bounded calls and requires a healthy local Linux engine. One healthy candidate is selected; several require an explicit `--runtime docker` or `--runtime podman`. No healthy candidate produces startup/installation guidance and a retry command instead of privileged installation or VM startup. Runtime discovery saves the local endpoint and never changes a global context. Remote Docker and non-loopback Podman connections are refused.

| Candidate environment | Current evidence |
| --- | --- |
| Linux amd64/arm64 + Docker Unix socket | Host guard and executable fake command contract only; no real image/install acceptance. |
| Linux amd64/arm64 + native local/rootless Podman | Host guard and executable fake command contract only; volume permissions/SELinux remain unverified. |
| macOS amd64/arm64 + local Docker Linux VM | Host guard and executable fake command contract only; local real engine is blocked upstream. |
| macOS amd64/arm64 + Podman loopback SSH machine | Explicit URI/identity snapshot has fake executable coverage; real machine, port forwarding and image behavior are unverified. |
| Windows, other architectures, remote engines | Refused by this preparation. |

First installation checks the requested unprivileged port (8080 by default), writes the private JSON manifest, installs the command bundle, creates an ownership-labeled named volume, pulls only the supplied image, creates one container and starts it. The prepared container has init, a read-only root, temporary `/tmp`, persistent `/var/data`, a 45-second stop timeout, restart policy and loopback-only port. It passes `PIPELINE_ORIGIN=http://localhost:PORT` and prints that URL only after the image healthcheck reports setup readiness. The port is checked again immediately before container creation; the engine remains the authority if another process wins the port between check and creation. `--ready-timeout` accepts 1–300 seconds (default 60) and bounds all polling subprocesses.

The [installation manifest contract](installation-manifest.md) defines saved fields, engine targeting, resource ownership, command bundle and interruption markers. A rerun uses that same manifest, endpoint, image, container and volume. It preserves existing configuration/data, starts a stopped container, and repairs a missing owned container only if its data volume remains. It refuses image/runtime/port changes, unowned resources and missing previously created data volumes. Nothing is removed on error. Interrupted pre-volume creation can resume; pull/start/readiness failures retain the named volume and provide management status/log guidance. A corrupt manifest or incomplete command bundle requires restoring the original files, rather than guessing ownership or resetting data.

## Verification and remaining gates

The installer tests use temporary executable Docker/Podman stand-ins with synthetic JSON engine state. They check explicit image validation, Linux-engine selection, multiple/failed runtimes, frozen endpoint and SSH identity, shell-free argv, container flags and origin/loopback port, custom-path command help/status/start/stop, data-preserving reruns, interrupted creation/pull, resource/schema mismatches, missing volume refusal, readiness deadlines, foreign command/symlink refusal and unsupported host guards. This proves the preparation's command and state boundaries; it does not prove either engine accepts these arguments or can run the image.

The historical October 7 combined run passed **82 tests, with 1 skipped**, in 25.23 seconds: **36 installer tests pass** and **46 management tests pass**. The skipped installer check would bind a real loopback socket to prove occupied-port behavior; the filesystem/network sandbox denies that bind. A separate deterministic fake-socket check verifies the exact loopback address, collision failure and unprivileged-port range. The run retains the existing Starlette TestClient deprecation warning. All installer/helper/management modules and both owned test files pass Ruff; strict mypy passes all three modules. Python syntax compilation, shell syntax, help-only bundle invocation and repository `git diff --check` pass. The existing native/browser baseline remains separately recorded in [integrated acceptance](integrated-acceptance.md), and cannot close installer acceptance.

October 8 recovery follow-up: `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_installer.py tests/test_management.py tests/test_operations.py tests/test_recovery_transfer.py` passes **150 tests, with 1 skipped**, in 54.79 seconds. It covers explicit fresh recovery registration, exact source image identity including Podman's bare hash form, retained source resources, private/independent destinations, completion markers, failed restore refusal, completed-restore create retry, installed recovered lifecycle/owner recovery, recorded data/config roots and nested-mount refusal. Six native transfer cases exercise real stdin extraction/T17 restore, unchanged owner-only backup bytes/modes, receiving-process ownership, manifest identity, symlink/hardlink refusal, insufficient temporary disk, elapsed deadline and a stalled receiver timeout. The native T17 cases preserve both databases, key, provenance/documents, session revocation and confirmed side-effect state. The skip remains the sandbox-denied real loopback bind; Starlette retains its deprecation warning. Owned Ruff, strict mypy, Python compilation, shell syntax, installer/management help and diff whitespace checks pass. These are simulated-engine and native checks, with all hosted/runtime/operator cells still open.

Reproduce the focused checks with the project's synced Python 3.12 environment:

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_installer.py tests/test_management.py
.venv/bin/python -m ruff check deploy/install.py deploy/pipeline_runtime.py deploy/pipeline_management.py tests/test_installer.py tests/test_management.py
.venv/bin/python -m mypy --strict deploy/install.py deploy/pipeline_runtime.py deploy/pipeline_management.py
sh -n deploy/install.sh
sh deploy/install.sh --help
```

Use a unique temporary test directory if several test runs share this workspace. The local recorded run used `/tmp/internship-pipeline-audit-venv/bin/python` and `--basetemp=/tmp/pipeline-t19-t20-tests-20261007-d` to avoid space-containing generated shebangs and shared temporary retention. This path is a local verification convenience, not an installer prerequisite.

T19 remains open until T18 supplies smoke-tested published versioned images and a declared supported matrix, the hosted artifact URL/name/integrity policy is approved and implemented, and a fresh supported host installs that exact artifact through readiness/browser setup. Real acceptance must include unavailable/stopped/multiple-runtime paths, port conflicts, volume permissions, interruption, same-data reruns, saved-context behavior and the installed management command after removing the checkout. Pull/start time and minimum resources must use measured T18 evidence. No commit, push, hosted publication, privileged installation, disk cleanup, reset, prune, external provider call or actual runtime action was performed here.
