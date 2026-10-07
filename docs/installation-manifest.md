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
| `image` | Explicit version tag or complete sha256 digest; no inferred tag, `latest`, `local`, `main`, `master`, `edge` or `dev`. The supplied image's publication and release provenance are a separate acceptance gate. |
| `port` | Integer from 1024 through 65535. |
| `origin` | Exactly `http://localhost:PORT`, passed as `PIPELINE_ORIGIN`. |
| `url` | Exactly the saved origin. The container publishes `127.0.0.1:PORT:8080`. |

The selected Docker context is read once to obtain its Unix socket; subsequent commands use literal `--host` arguments. TCP, SSH and remote Docker endpoints are outside this preparation. Podman saves its selected default/named connection URI and explicit SSH identity when applicable. Only native local mode, local Unix sockets and SSH loopback connections are candidates. Native Podman uses `--remote=false`; an explicit endpoint uses `--url`, with `--identity` for SSH. Docker/Podman connection environment variables are removed for saved-runtime commands, so later global context or environment changes cannot redirect an existing installation. Runtime discovery never selects a new global context or changes connection configuration. The CLI must report a Linux engine before provision or lifecycle actions.

Prepared command flags follow the official [Docker create reference](https://docs.docker.com/reference/cli/docker/container/create/) and [Podman remote client reference](https://docs.podman.io/en/stable/markdown/podman-remote.1.html). Documentation checks support the proposed argument contract; the executable fixtures remain simulated, and actual engine compatibility is a separate gate.

## Resource ownership and interruption

Both resources carry `io.internship-pipeline.install-id=UUID`. Before any lifecycle action, runtime inspection verifies the label, exact configured image, one `/var/data` mount from the named volume, and the exact loopback port mapping. It refuses missing ownership, malformed inspection data or changed storage/image/port. Failed inspection is not assumed to mean absence: a bounded resource listing first confirms whether the name exists.

The installer exclusively writes the manifest before creating engine resources. After successful owned volume creation/inspection, it writes `.volume-created` containing the installation UUID. A rerun without that marker can finish volume creation only while the saved container is absent. Once the marker exists, a missing volume is a recovery failure; the installer never replaces it with an empty volume. The marker is written before any application container is created or started. Failed pulls, creation, startup or readiness leave the manifest and volume intact. An owned missing container can be recreated using the same manifest/image/volume; an owned stopped container is started without pulling or replacing it.

`.installer.lock` uses a nonblocking advisory lock to serialize installer runs for this root. The `command/` bundle has `.installation-id` and the three copied management files; its marker must match the manifest. The installed command symlink must point to this bundle. Existing foreign directories, commands, resources and unsafe command files are refused. Reruns never overwrite the bundle or modify saved image/runtime/port. Interrupted or damaged bundle copies require restoration from the same reviewed bundle rather than automatic overwrite.

The manifest, markers and command bundle identify the local installation; application configuration, credential encryption key, SQLite files, uploads and generated documents live inside the named volume. Preserve the local root **and** the complete T17 backup when recovering. Neither an installation manifest nor a volume name is an application backup. Automatic image updates and restored-subdirectory registration are not implemented.

## Shared host API

`RuntimeSpec`, `Manifest`, `load_manifest`, `Runtime.check`, `Runtime.inspect_volume`, `Runtime.inspect_container`, `Runtime.require_owned` and `wait_ready` are shared by installation and management. `Runtime.run(*argv, timeout=...)` passes literal argument vectors without a shell, captures engine output privately, and reports generic safe failures. Routine operations use 15-second timeouts, initial context/connection discovery uses 10 seconds, pull uses 600 seconds, create uses 60 seconds and start uses 30 seconds. The readiness helper uses a monotonic deadline and caps every inspection subprocess by the remaining budget. Accepted engine stdout is limited to 2 MiB after capture; this is not a streaming memory limit. No image/container logs or first-run setup token are printed by the installer.

Readiness means the image's healthcheck reports `healthy`, which the prepared T18 image defines through `/readyz` with the configured origin. It does not mean guided setup has been completed, collection has produced a result or external providers work. Actual healthcheck/volume/port compatibility is unverified until T18 and T19 run against real published images on declared hosts.
