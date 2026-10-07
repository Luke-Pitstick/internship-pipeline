# T03 follow-up — actual single-container acceptance

October 6, 2026. **Status: blocked for actual container acceptance.** An authorized existing Colima profile reached a responsive Linux arm64 Docker engine, but its QEMU VM paused with a disk `nospace` error during the actual image build. No image build or application container lifecycle passed. This remains T03 work and is not deferred to T18.

## Runtime diagnosis

- Host CLI reports Docker Engine Community client **29.2.1**, API **1.53**, **darwin/arm64**, with context **desktop-linux**. Docker Desktop is installed under `/Applications/Docker.app`; the context's socket exists at the user's `.docker/run/docker.sock`. Server version, server architecture and image ID are unavailable because the engine did not respond.
- A sandbox `docker version` reached the client but returned a socket permission error. That establishes a sandbox boundary, not engine health.
- A separately approved host-access `docker info`, bounded with Python `subprocess.run(..., timeout=15)`, timed out after 15 seconds. A read-only host process inventory showed Docker Desktop, backend, build and virtualization processes already running. Starting an installed runtime was therefore unnecessary. No GUI binary was launched, and no runtime restart, kill, reset or prune was attempted.
- The finished runner was invoked separately with approved host Docker access: `rtk proxy python deploy/container-smoke.py`. It exited **1** with exactly `BLOCKED/FAILED: Docker info exceeded 15s`. Its engine preflight precedes build/resource creation; this run created no image, container or volume and emitted no setup token or account secret.
- T18's later approved read-only host check again timed out, now after 10 seconds. Bounded alternative-runtime checks found installed Podman unavailable (exit 125) and Colima unavailable (exit 1). No runtime was started/restarted/reset/pruned and no local privileged package was installed. The T03 engine gate remains open.

The follow-up inspected actual profiles rather than repeating that diagnosis. Podman had no machine or connection; the existing Colima default QEMU/aarch64 profile was stopped and had a persistent root disk. `rtk proxy colima start --profile default --activate=false --save-config=false --ssh-config=false` started that existing profile. An explicit `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`, with `DOCKER_CONTEXT` removed for the command, returned **Docker Engine 29.2.1, Linux arm64, 2 CPUs, 2,050,961,408 bytes RAM, zero containers and zero images**. The user's saved global Docker context remained `desktop-linux`.

The actual command was `rtk proxy env -u DOCKER_CONTEXT DOCKER_HOST=unix://$HOME/.colima/default/docker.sock python3 deploy/container-smoke.py --platform linux/arm64 --recovery --report /tmp/pipeline-colima-arm64-evidence.json`. It began building `pipeline-t03-f0c5b3c7c431:smoke`, then Docker and guest SSH diagnostics timed out. Read-only QEMU monitor queries established `query-status = {"status":"io-error","running":false}` and the root `virtio0` block device's `io-status = "nospace"`; the raw disk had a 100 GiB virtual size and 5,597,122,560 allocated bytes. Host APFS then reported about 7 GiB free, and `memory_pressure -Q` reported 40% free; the evidence is a disk I/O failure, not a proven RAM shortage or Dockerfile defect. No image ID/report or application container/volume creation was reached. Only the positively identified smoke-build/query clients were interrupted, and the runner exited **1**, `BLOCKED/FAILED: Docker build failed (exit 130)`.

Colima's routine startup regenerated its Lima configuration, automatically expanded its root disk from 20 GiB to the profile's saved 100 GiB disk setting, dropped the previous `additionalDisks` reference, and refreshed guest binfmt registrations despite `--save-config=false`. The final `_disks/colima` directory contains metadata only; the old reference was not proof that a separate data image existed. Those state changes are retained and explicitly recorded; no disk shrink, deletion, reset or prune was requested. Cleanup stops only the profile started by this attempt, retaining its verified root disk and partial build cache. See [T18 runtime evidence](t18-portable-images.md) for the final stop result.

## Runnable acceptance

On a host where `docker info` responds, from the project root:

```sh
rtk proxy python deploy/container-smoke.py
```

The runner uses Python's standard library and the installed Docker CLI. Every Docker operation has a deadline; engine preflight is 15 seconds, readiness is 60 seconds, and image build defaults to 1,200 seconds (`--build-timeout SECONDS` can adjust it). Build output and application logs are captured privately in memory and are never printed, including on failure. No host environment variables are forwarded into the container except the generated loopback origin. It mounts a fresh named volume, uses a unique `pipeline-t03-<random>` image/container prefix, and prints sanitized pass evidence and the built image ID.

The actual run is designed to prove:

| Acceptance | Current result | Runner check |
| --- | --- | --- |
| Current image builds | Actual build attempted; blocked by QEMU disk `nospace` pause, then interrupted | Build the current source and locked dependencies/frontend |
| Built frontend and API share one port | Not run | Loopback-only mapping; serve `/`, referenced frontend assets and `/healthz` |
| Readiness without profile/models/integrations | Not run | Fresh volume returns setup readiness and no active worker roles |
| Anonymous private requests denied | Not run | Jobs, status and resume routes return 401 |
| Single-use claim, login/logout | Not run | Consume logged setup token once; repeat claim fails; logout revokes access; wrong password fails; correct login succeeds |
| Actual filesystem ownership and writes | Not run | Execute as image UID 10001, check ownership of both SQLite DBs, write/commit a synthetic marker in the jobs DB |
| Same-volume persistence and readiness recovery | Not run | Stop/start the same container; owner, session and marker persist; claim remains closed; no new token; owner readiness and frontend/API recover |
| Graceful signals | Not run | SIGTERM through `docker stop` and SIGINT through `docker kill --signal SIGINT` both reach stopped state with exit 0 and no OOM |
| Isolated cleanup | Offline runner test passed only | Finally remove only the generated container, volume and image tag; report own resources needing attention if cleanup fails |

The synthetic marker uses a separate `t03_smoke` table inside the fresh disposable jobs database; it never opens an existing installation. The container mirrors Compose's non-root user, init, read-only root, `/tmp` tmpfs and `/var/data` volume. This does not certify other architectures or Podman, and does not run models, send notifications, deploy or publish anything.

## Checks completed

- `rtk proxy .venv/bin/python -m pytest -q tests/test_container_smoke.py`: **4 passed**. These offline tests check secret-free Docker failures/timeouts, same-origin relative asset resolution, and cleanup of only uniquely created resources after failure. They do **not** prove a container ran.
- `rtk proxy .venv/bin/ruff check deploy/container-smoke.py tests/test_container_smoke.py`: passed.
- `rtk proxy .venv/bin/python -m py_compile deploy/container-smoke.py`: passed.
- `rtk proxy docker compose config --quiet`: passed; static configuration acceptance only.
- `rtk git diff --check`: passed.

T18 preparation now adds image readiness health, frontend checking during build, OCI version/revision/source labels and a narrower source-only build context. Compose's default origin follows an overridden `PIPELINE_PORT`; static parsing verified mapping and origin both use 18080. The runner supports an explicitly supplied local image/platform and optional `--engine podman`; support claims still require actual execution. Its safe post-claim expectation follows the current independent search/email/Sheets roles. The updated **five** offline runner tests pass. The additional native recovery fixture test passes separately, for **six** focused tests total, and its actual image journey is exposed by `--recovery`. These changes are preparation and cannot claim a packaging defect repaired without a build. See [T18 portability evidence](t18-portable-images.md).

## Remaining assignment

The host operator must provide sufficient disk headroom and recover the paused Colima profile, restore Docker Desktop responsiveness, or select another healthy authorized Docker host. A responsive idle `docker info` alone is now known to be insufficient: the engine must remain responsive through the current image build. Then run the isolated acceptance and retain its image ID and sanitized result. The failed attempt does not establish a numerical minimum disk requirement, architecture certification, or a packaging failure; it establishes the exact QEMU disk I/O blocker.
