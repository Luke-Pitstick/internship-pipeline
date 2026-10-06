# T03 follow-up — actual single-container acceptance

October 6, 2026. **Status: blocked for actual container acceptance.** The bounded diagnosis and runnable acceptance runner are complete; no actual image build/container lifecycle passed. This remains T03 work and is not deferred to T18.

## Runtime diagnosis

- Host CLI reports Docker Engine Community client **29.2.1**, API **1.53**, **darwin/arm64**, with context **desktop-linux**. Docker Desktop is installed under `/Applications/Docker.app`; the context's socket exists at the user's `.docker/run/docker.sock`. Server version, server architecture and image ID are unavailable because the engine did not respond.
- A sandbox `docker version` reached the client but returned a socket permission error. That establishes a sandbox boundary, not engine health.
- A separately approved host-access `docker info`, bounded with Python `subprocess.run(..., timeout=15)`, timed out after 15 seconds. A read-only host process inventory showed Docker Desktop, backend, build and virtualization processes already running. Starting an installed runtime was therefore unnecessary. No GUI binary was launched, and no runtime restart, kill, reset or prune was attempted.
- The finished runner was invoked separately with approved host Docker access: `rtk proxy python deploy/container-smoke.py`. It exited **1** with exactly `BLOCKED/FAILED: Docker info exceeded 15s`. Its engine preflight precedes build/resource creation; this run created no image, container or volume and emitted no setup token or account secret.

## Runnable acceptance

On a host where `docker info` responds, from the project root:

```sh
rtk proxy python deploy/container-smoke.py
```

The runner uses Python's standard library and the installed Docker CLI. Every Docker operation has a deadline; engine preflight is 15 seconds, readiness is 60 seconds, and image build defaults to 1,200 seconds (`--build-timeout SECONDS` can adjust it). Build output and application logs are captured privately in memory and are never printed, including on failure. No host environment variables are forwarded into the container except the generated loopback origin. It mounts a fresh named volume, uses a unique `pipeline-t03-<random>` image/container prefix, and prints sanitized pass evidence and the built image ID.

The actual run is designed to prove:

| Acceptance | Current result | Runner check |
| --- | --- | --- |
| Current image builds | Not run: engine preflight blocked | Build the current source and locked dependencies/frontend |
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

No Dockerfile/Compose changes were necessary from static inspection, and no packaging defect can be claimed resolved without an actual build. Existing application/bootstrap changes from the other task owners were preserved.

## Remaining assignment

The parent/T03 owner must obtain a responsive Docker engine, either by having the host operator restore Docker Desktop health or by selecting another authorized working Docker host. First verify `docker info` responds; then run the command above and retain its sanitized output, host/runtime and image ID. Repair any concrete build/lifecycle failure within T03 and rerun until every actual acceptance row passes. Restoring the host runtime is the precise external action blocking this follow-up; merely granting sandbox socket permission does not resolve the observed host-access timeout.
