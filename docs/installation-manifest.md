# Host installation contract

October 7, 2026. This schema belongs to the local T19/T20 preparation. It is not evidence of a published image or a supported runtime. The installer and management command share `deploy/pipeline_runtime.py`; neither sources the manifest as shell code.

## Saved identity

The private default root is `~/.local/share/internship-pipeline`. A different absolute path can be selected with `--install-dir`. `installation.json` must be a regular file owned by the invoking user, with no group/other write permission and a maximum size of 64 KiB. The installer writes mode 0600. Schema 1 has these exact top-level fields:

| Field | Contract |
| --- | --- |
| `schema_version` | Integer `1`; other schemas are refused. |
| `install_id` | A generated UUID identifying this installation. |
| `runtime` | Object with `name` (`docker` or `podman`), absolute CLI `executable`, saved local `endpoint`, and `identity` (Podman SSH identity path, otherwise empty). No credentials or private key contents are stored. |
| `container_name` | `internship-pipeline-` followed by the full installation UUID. |
| `volume_name` | Container name followed by `-data`. |
| `image` | Ordinary install: explicit version tag or complete registry sha256 digest. Fresh recovery: exact inspected local `sha256:CONFIG_ID`, retained by `--pull never`. No inferred tag, `latest`, `local`, `main`, `master`, `edge` or `dev`. Local config IDs are not registry manifest digests. |
| `port` | Integer from 1024 through 65535. |
| `origin` | Exactly `http://localhost:PORT`, passed as `PIPELINE_ORIGIN`. |
| `url` | Exactly the saved origin. The container publishes `127.0.0.1:PORT:8080`. |
| `data_dir` | Required; exactly `/var/data` for ordinary installation or `/var/data/restored` for explicit fresh recovery. The application receives this value as `PIPELINE_DATA_DIR` and `<data_dir>/config/settings.yaml` as `PIPELINE_CONFIG`. Old development manifests without this field are refused; there is no migration. |

The selected Docker context is read once to obtain its Unix socket; subsequent commands use literal `--host` arguments. TCP, SSH and remote Docker endpoints are outside this preparation. Podman saves its selected default/named connection URI and explicit SSH identity when applicable. Only native local mode, local Unix sockets and SSH loopback connections are candidates. Native Podman uses `--remote=false`; an explicit endpoint uses `--url`, with `--identity` for SSH. Docker/Podman connection environment variables are removed for saved-runtime commands, so later global context or environment changes cannot redirect an existing installation. Runtime discovery never selects a new global context or changes connection configuration. The CLI must report a Linux engine before provision or lifecycle actions.

Prepared command flags follow the official [Docker create reference](https://docs.docker.com/reference/cli/docker/container/create/) and [Podman remote client reference](https://docs.podman.io/en/stable/markdown/podman-remote.1.html). Documentation checks support the proposed argument contract; the executable fixtures remain simulated, and actual engine compatibility is a separate gate.

## Resource ownership and interruption

Both resources carry `io.internship-pipeline.install-id=UUID`. Before any lifecycle action, runtime inspection verifies the label, exact configured image, one `/var/data` mount from the named volume, the recorded data/config environment values, and the exact loopback port mapping. Extra mounts beneath `/var/data` are refused because they can redirect the restored data. It refuses missing ownership, malformed inspection data or changed storage/image/port. Failed inspection is not assumed to mean absence: a bounded resource listing first confirms whether the name exists.

The installer exclusively writes the manifest before creating engine resources. After successful owned volume creation/inspection, it writes `.volume-created` containing the installation UUID. A rerun without that marker can finish volume creation only while the saved container is absent. Once the marker exists, a missing volume is a recovery failure; the installer never replaces it with an empty volume. The marker is written before any application container is created or started. Failed pulls, creation, startup or readiness leave the manifest and volume intact. An owned missing container can be recreated using the same manifest/image/volume; an owned stopped container is started without pulling or replacing it.

`.installer.lock` uses a nonblocking advisory lock to serialize installer runs for this root. The `command/` bundle has `.installation-id` and the three copied management files plus the MIT `LICENSE` notice; its marker must match the manifest. The installed command symlink must point to this bundle. Existing foreign directories, commands, resources and unsafe command files are refused. Reruns never overwrite the bundle or modify saved image/runtime/port. Interrupted or damaged bundle copies require restoration from the same reviewed bundle rather than automatic overwrite.

The manifest, markers and command bundle identify the local installation; application configuration, credential encryption key, SQLite files, uploads and generated documents live inside the named volume. Preserve the local root **and** the complete T17 backup when recovering. Neither an installation manifest nor a volume name is an application backup. Automatic image updates are not implemented.

## Explicit fresh recovery

`--restore-from PRIVATE_BACKUP --restore-source STOPPED_INSTALL_ROOT` uses a new installation root, command directory, UUID, labelled volume, container and distinct loopback port. The retained source must have a valid owned manifest, volume and stopped container. Its saved runtime supplies the endpoint/SSH identity; its inspected local image ID supplies both offline restore and destination creation, without pulling or following a movable tag. The host owner reads the owner-only backup into a private temporary tar; only the new volume is mounted in the non-root restore container, which receives the archive through stdin. Regular-file/directory extraction uses `tarfile.data_filter` and private modes into `/var/data/backup`; its manifest SHA-256 is checked before T17 validates all contents and restores into `/var/data/restored`. No host bind, permission/ownership change or UID-namespace override is needed. Host temporary disk and fresh-volume space for both copied backup and restored data are required. Recovery does not adopt arbitrary existing volumes or mutate the source.

`.restore-started` is written before invoking restore; `.restore-completed` is written only after a successful exit. Both contain the destination UUID and have owner-only permissions. `.backup-manifest.sha256` records the successfully transferred backup identity. The app container is never created before completion. A completed restore can resume interrupted container creation/start with the normal installer rerun, without restoring or pulling again. A started restore without confirmed completion fails closed, including after a crash between restore exit and marker creation. Preserve that volume; use another new root/command directory/port for a deliberate new restore instead of deleting markers or retrying against uncertain data. Installed management refuses a restored installation without a valid completion marker. Owner/token maintenance uses the recorded restored root.

This contract covers exact-image recovery on the same saved engine. Moving to another engine/host, deleted source containers or unavailable exact local images requires separately accepted image import and destination registration; it is not silently inferred here. Fresh first-release installations and recovery from their complete same-image backup are supported design targets; upgrades from old development snapshots and cross-release schema/downgrade compatibility are excluded.

## Shared host API

`RuntimeSpec`, `Manifest`, `load_manifest`, `Runtime.check`, `Runtime.inspect_volume`, `Runtime.inspect_container`, `Runtime.require_owned` and `wait_ready` are shared by installation and management. `Runtime.run(*argv, timeout=...)` passes literal argument vectors without a shell, captures engine output privately, and reports generic safe failures. Routine operations use 15-second timeouts, initial context/connection discovery uses 10 seconds, pull uses 600 seconds, create uses 60 seconds and start uses 30 seconds. The readiness helper uses a monotonic deadline and caps every inspection subprocess by the remaining budget. Accepted engine stdout is limited to 2 MiB after capture; this is not a streaming memory limit. The installer never prints raw image/container logs. It deliberately prints a private browser setup link for an unclaimed instance; keep installer output private.

Readiness means the image's healthcheck reports `healthy`, which the prepared T18 image defines through `/readyz` with the configured origin. It does not mean guided setup has been completed, collection has produced a result or external providers work. Actual healthcheck/volume/port compatibility is unverified until T18 and T19 run against real published images on declared hosts.
