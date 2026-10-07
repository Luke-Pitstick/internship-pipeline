# T01–T20 operations implementation review

October 7, 2026. Independent GPT-6.1 Sol high review of `e9f4c012ef3c14f709abe7a20ab416fdebff13c2` plus the current uncommitted/untracked implementation, including all five T19/T20 deploy files. This report owns installation/runtime/supervisor/diagnostics/backup/recovery/packaging/CI/deployment contracts; backend and HTTP/UI findings belong to the parallel reviewers. Production code, tests, dependencies, private inputs, and actual engines were not changed or operated.

Four reproducible P2 findings remain in this scope. The most consequential is a backup that reports success while copying the wrong SQLite database for a valid filesystem path. No P0 or P1 finding was established in this operations slice. Declared image/platform/hosting gaps are recorded separately, not upgraded into demonstrated implementation defects.

## Findings

### 1. [P2] Encode filesystem paths before using SQLite URI syntax

**Primary location:** [operations.py:81](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/operations.py:81>). The same construction also appears in backup verification at [operations.py:212](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/operations.py:212>).

**Trigger and impact:** Back up an otherwise valid native installation whose directory contains a literal `?`, such as `/tmp/persistent?synthetic`. `_snapshot` interpolates the raw path into `file:...?...` and enables SQLite URI parsing. SQLite interprets part of the filename as query syntax, opens or creates the truncated filename, and snapshots that different database. Integrity checking an empty SQLite database returns `ok`, and credential checking skips absent credential tables, so the full backup and its verification both report success despite losing the application schema/data. The resulting recovery set cannot restore the installation. This path is legal on the proposed Linux/macOS hosts; the CLI neither rejects it nor warns that it cannot preserve it.

**Evidence, high confidence:** A synthetic installation created with the real `Store`, `Identity`, `Settings` and a newly generated test encryption key produced:

```text
question-mark original state has tasks: True
question-mark backup succeeds: 4
question-mark backup verifies: True
question-mark backed-up state has tasks: False
question-mark restore fails: OperationalError no such table: tasks
```

The original database remained intact. Only temporary directories and synthetic state were involved. Reproduction is in `/tmp/pipeline-operations-repros.py`.

**Minimal fix direction:** Build the SQLite URI from an absolute, correctly escaped file URI before appending `?mode=ro`, in both snapshot and verification. Verify expected application/identity schema presence so an internally consistent empty or unrelated database cannot satisfy a complete-installation backup check. Add a meaningful restore test with a legal path containing `?`, proving identity/job data survive and no alternate SQLite file is created.

### 2. [P2] Preserve stderr lifecycle events in the management log summary

**Primary location:** [pipeline_runtime.py:213](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/deploy/pipeline_runtime.py:213>), used by [pipeline_management.py:281](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/deploy/pipeline_management.py:281>).

**Trigger and impact:** Run the installed host `internship-pipeline logs` command after a worker exits or fails to start. The supervisor emits the recognized lifecycle messages on `sys.stderr`, including [supervisor.py:82](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/supervisor.py:82>). The runtime helper captures both streams but returns only stdout. A logs command preserving the container's stderr stream therefore loses exactly the failure events the manager promises to summarize, even reporting zero omitted lines. The owner gets an empty successful diagnostic result when the process tree is failing.

**Evidence, high confidence:** A standalone executable fake engine returned valid Linux-engine/resource inspections and exit status zero, then emitted `Worker matcher exited unexpectedly: 7` on stderr for its logs command. Calling the real `manage(..., command='logs')` returned:

```text
{'events': [], 'omitted_lines': 0}
```

This proves the helper drops successful-command stderr without operating an engine. Existing fake-engine log tests emit their messages on stdout, so they don't catch the stream boundary.

**Minimal fix direction:** Give log capture a dedicated path that feeds both successful-command output streams through `runtime_log_summary`. Keep inspection JSON on stdout and keep engine failures sanitized; concatenating arbitrary stderr into every runtime result would break the JSON contract and risk private output. Add a fake-engine test with the recognized event on stderr and unrecognized secret-looking lines in both streams.

### 3. [P2] Replace the shipped settings file that the current application rejects

**Primary location:** [deploy/settings.yaml:3](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/deploy/settings.yaml:3>), with the obsolete group at lines 6–10.

**Trigger and impact:** Select the supplied deployment YAML through `PIPELINE_CONFIG`, copy it to the documented `/var/data/config/settings.yaml`, or use it with the application's `--config` option. The current `Settings` model forbids extra fields, but this file still includes removed candidate, Codex-generation, notification and outbox settings. Startup fails during settings loading, before owner setup/readiness, and CLI commands using this configuration fail too. Fresh Compose defaults don't consume this file, so this is a broken supplied configuration path rather than a claim that every default installation fails.

**Evidence, high confidence:** The real `load_settings(Path('deploy/settings.yaml'))` raises:

```text
Invalid settings fields: profile_path, resume_model, resume_reasoning_effort,
notification_urls, recording_notifications_path, dot_outbox_path
```

`runtime_settings` uses the same loader; bootstrap calls it before initializing the application. Reproduction is synthetic/read-only and requires no engine.

**Minimal fix direction:** Remove the obsolete fields and retain only the current operational `Settings` contract; don't reintroduce fallback acceptance or import private candidate inputs. Validate the shipped configuration in a targeted test. Separately, current Render instructions still describe a retained Codex résumé worker and unavailable browser profile/model editing, and `render.yaml` still contains `CODEX_HOME`; reconcile those objective documentation/configuration leftovers with the current application when removing obsolete deployment paths.

### 4. [P2] Document offline recovery instead of executing recovery inside the active container

**Primary location:** [docs/deployment.md:24](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/docs/deployment.md:24>); the same failure affects the account command at [docs/deployment.md:30](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/docs/deployment.md:30>) and the running operator-shell recipe in [docs/render-deployment.md:5](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/docs/render-deployment.md:5>).

**Trigger and impact:** Follow the current deployment instructions after losing an unclaimed setup token or owner password. They prescribe `docker compose exec app internship-pipeline setup-token` / `recover-owner`, which require the application container to be running. Bootstrap holds a shared installation lock for its entire lifetime at [bootstrap.py:104](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/bootstrap.py:104>), while both recovery commands require an exclusive offline lock at [cli.py:356](</Users/lukepitstick/Documents/ChatGPT/Internship Pipeline/src/internship_pipeline/cli.py:356>). The advertised recipes cannot proceed even on a healthy engine, leaving the owner unable to recover by following that document.

**Evidence, high confidence:** Holding the real `installation_lock` in a temporary synthetic root and invoking the real CLI yielded exit 2 for both commands and `Stop the application and all workers before backup or recovery.` No password prompt or public recovery bypass was used. T17/T19/T20 documentation correctly states the offline contract, which makes the older deployment recipes contradictory rather than an implementation reason to weaken the lock.

**Minimal fix direction:** Replace these recipes with a complete sequence that stops supported writers, invokes the exact image's maintenance CLI in a one-off container mounting the same preserved data volume, and restarts after recovery. Use the saved endpoint for installed deployments. Keep the exclusive lock and absence of a public recovery endpoint. Provide a stopped-instance Render procedure or explicitly state the required platform recovery capability instead of suggesting the active shell command works.

## Coverage and positive evidence

The review read the current supervisor/bootstrap/maintenance CLI; `operations.py`; installer shell/Python/launcher, shared runtime and management client; Dockerfile, build context allowlist, Compose, Render configuration; both CI workflows; container smoke runner and recovery fixture; targeted installer/manager/operations/supervisor/bootstrap/container-tooling tests; T03/T17/T18/T19/T20 handoffs; task definitions, installation-manifest contract, product plan and release-readiness matrix. Graph inventory had no index for this checkout, so discovery used narrow `rg` searches without reindexing or uploading source. The security-review skill informed input, filesystem, credential and diagnostic boundaries; HTTP authorization ownership remained with the web reviewer.

| Contract checked | Result within this review |
| --- | --- |
| Saved endpoint/global runtime context | Shared helper saves explicit Docker Unix/Podman local endpoints, strips connection environment overrides, and passes literal argv. Fake-runtime checks pass; no global context mutation occurs in installer/manager source. |
| Resource ownership and preservation | UUID labels, expected image, data mount and loopback binding are checked before lifecycle changes. Existing-volume marker prevents automatic empty replacement; reruns retain saved image/port/runtime. Confirmed by synthetic tests and source inspection. |
| Installer failures and command portability | Manifest is recorded before engine resources; failed pulls retain state. Foreign commands, manifest symlinks and unsafe bundle files are refused. Copied launcher resolves its own bundle/installation rather than the checkout. Python 3.12+ remains a documented dependency. |
| Bounded operations and shutdown | Runtime calls and readiness inspections have finite deadlines. Native supervisor tests exercise signal handling, stubborn children and process groups. Captured output has a post-capture limit, expressly not a streaming memory bound. |
| Authenticated diagnostics and secret output | Host client uses an ephemeral cookie jar, CSRF login, no redirects/proxies, hidden password prompt, bounded response and enum/value allowlist. Native TestClient and synthetic failure cases pass. No actual browser/serving-container login occurred. |
| Complete stopped-directory recovery | Native tests preserve both DBs, exact synthetic encrypted credentials, uploads/provenance, byte-identical compiled master/tailored PDFs, confirmed delivery/checkpoint state, session revocation and fresh-only restore. They also exercise copy failure cleanup, symlink/hash/key refusal and exclusive-lock denial. These passes don't cover the path defect above. |
| Container packaging/CI | Dockerfile builds static frontend separately, installs frozen Python dependencies/TeX, uses UID 10001 and prepares `/var/data`; Compose sets loopback/origin/read-only/tmpfs/init/grace period. Native amd64/arm64 Docker/Podman CI, OCI/SBOM/provenance export and comparison are prepared. Actual acceptance was not executed here. |

The backend reviewer owns confirmed-delivery replay on queue interruption and saved-search/legacy-collector interaction. This report does not duplicate those findings or infer integration correctness solely from preserved backup rows. Generic CLI retry can requeue failed integration tasks; its behavior needs to be considered alongside those integration contracts rather than treated as proof that uncertain external effects are safe to resend.

## Commands and limits

Authoritative targeted test run:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/test_installer.py tests/test_management.py \
  tests/test_operations.py tests/test_supervisor.py tests/test_bootstrap_app.py \
  --basetemp=/tmp/pipeline-operations-review-tests-repeat
```

Result: **98 passed, 1 skipped, 1 failed**, in 31.85 seconds. The skip is the installer socket-bind check; the failure is `test_real_supervisor_setup_restart_and_graceful_shutdown` at its initial `127.0.0.1` bind, which raises sandbox `PermissionError: [Errno 1] Operation not permitted`. That is an environmental verification limit, not a demonstrated bootstrap defect. The process-based supervisor tests, TestClient auth checks, fake runtime tests and synthetic operations recovery checks passed. The full result is deliberately not called green.

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/test_container_smoke.py \
  tests/test_container_recovery_fixture.py \
  --basetemp=/tmp/pipeline-operations-review-container-tooling
```

Result: **6 passed**, in 1.34 seconds. The recovery fixture really uses native child interruption and synthetic compiled PDF/database recovery; Docker/Podman operations in tooling tests are mocked. No container ran.

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python /tmp/pipeline-operations-repros.py
```

This temporary script reproduces all four findings using only the real native Python APIs, a standalone fake executable and self-cleaning synthetic directories. It prints no generated key/token or personal data. Source reads, line-number checks and current Git status/diff scope were also inspected. No full suite, frontend build/browser suite, lint/type gate, actual Compose validation, live provider, image build/pull/run, engine startup/reset/prune, volume deletion, publication or deployment was performed by this reviewer.

## Residual verification gaps

T03 actual image lifecycle and T17 actual container interruption/fresh-volume restore remain unproved. T18 native amd64/arm64 Docker/rootless-Podman matrix execution, UID/volume permissions, image export digest comparison, dependency attestations, registry publication and named-host resource measurements remain unproved. T19 hosted immutable artifact and real first install/rerun require an accepted image and final URL; T20 installed-image lifecycle/HTTP diagnostics and platform-specific backup mounts require the same evidence. Existing stopped Colima and unresponsive Desktop state were left untouched. Numerical host requirements and supported-platform claims cannot be derived from these fake/native checks.

These gaps are already disclosed in the handoffs/readiness matrix. They are release acceptance work, separately from the concrete bugs above. Cross-release migration/downgrade and automatic registration of restored subdirectory roots are also expressly unimplemented; this report does not demand compatibility layers or classify those disclosed limits as new defects.
