# R4 — Data and operations repairs

October 8, 2026. **Implemented and locally verified; independent R5 review and actual
container acceptance remain open.** Dispatch HEAD was
`3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`; the parent recorded 608 Python baseline
passes before production edits. This lane's evidence describes the uncommitted working
tree, with concurrent backend/web repairs preserved. No release gate is certified here.

## Defect-specific red and green evidence

The first regression run used:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q \
  tests/test_sheets_integration.py tests/test_operations.py tests/test_management.py \
  tests/test_deployment_contract.py \
  -k 'complete_stable_inventory or inventory_capacity or reserved_paths or wrong_database or stderr_lifecycle or shipped_operational or deployment_documents' \
  --basetemp=/tmp/pipeline-r4-red-20261008 --tb=short
```

Result before the corresponding production repairs: **14 intended failures, 3 passes**
in 8.01 seconds. The assertions exposed each original finding rather than fixture/setup
errors. The first repaired subset then passed **16 tests** in 7.20 seconds; the excluded
documentation assertion was completed with the O4 documentation repair.

| ID | Actual failing regression | Repair and retained evidence |
| --- | --- | --- |
| B5 | A 10,003-job CSV lacked its final three IDs. A 10,001-job Sheets preview succeeded instead of raising the expected explicit capacity error. The 10,000 boundary passed. | CSV iterates every job in stable ID order and emits bounded chunks from one read snapshot. Sheets facts stop with an explicit 10,000-job error, destination allocation rejects overflow before saving a partial plan, and queue admission rechecks inventory capacity. All original formula/ownership/fingerprint tests remain. |
| O1 | Literal `?` and `#` installation paths reported successful backups whose state database lacked `tasks`. Verification accepted six hash-valid empty, unrelated, or swapped database variants. Space/Unicode paths already passed. | Read-only SQLite opens use `Path.resolve().as_uri()` before appending URI parameters. Both snapshot and verification check integrity and the required base tables/columns from the actual Store and Identity schemas. Tests preserve task data and owner login through backup/restore for all three path variants, reject wrong source databases before publication, and reject hash-valid wrong backups for both identities. |
| O2 | Both Docker and Podman fake-engine stderr lifecycle tests omitted the matcher start failure. | Logs capture stdout and stderr, apply the combined inspection size limit, and feed both to the existing event allowlist. Normal JSON commands still receive stdout only. Both-stream secrets are omitted; the existing engine-error test proves failure stderr is not printed. |
| O3 | Strict loading of `deploy/settings.yaml` rejected six obsolete profile/model/notification/outbox fields. | Removed those fields and aligned its default state path with the current application. Both shipped operational examples pass the actual strict loader. Render's `CODEX_HOME` and obsolete worker/browser claims were removed; current Settings and independent worker contracts are documented. |
| O4 | The durable documentation assertion found active-container `compose exec` recovery recipes. | Compose now stops writers, pins a one-off maintenance container to the inspected image ID and preserved service volume with no network/pull, and restarts only after success. Installed host recovery uses its saved endpoint/volume and the stopped container's exact inspected image ID, literal argv, no pulls/network, and an interactive terminal. It refuses a running application and leaves it stopped until explicit start. Render explicitly requires exclusive stopped-disk maintenance capability and retains its acceptance gap. |

Additional retained regressions caught boundary issues during implementation:

- **Sheets admission after growth:** preview one job, grow to 10,001, then request sync.
  Before its admission repair, the expected error failed to occur; after repair, the run
  remains a preview and no sync task or remote write is created.
- **Sequential streaming thread hops:** two real native thread pools consumed successive
  CSV chunks. The first implementation raised SQLite `ProgrammingError`; CSV now owns
  a dedicated read-only `check_same_thread=False` connection, serial iteration and a
  finally-close boundary, preserving one snapshot across Starlette's pool hops.
- **Exact recovery image:** fake Docker/Podman returned an inspected image ID different
  from the manifest tag. Four assertions initially saw the tag in maintenance argv;
  the repaired command pins the inspected ID and disables image pulls.
- **Offline lock:** real native `installation_lock` rejects both setup-token and owner
  recovery while active, preserves the original setup-token hash, and allows token
  rotation/claim after the lock is released. Existing native owner recovery/session
  revocation coverage is preserved. The new token test checks the stored hash because
  `setup_token()` deliberately does not retrieve an already-issued plaintext token.

## Final local verification

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q \
  tests/test_sheets_integration.py tests/test_operations.py tests/test_management.py \
  tests/test_installer.py tests/test_deployment_contract.py tests/test_container_smoke.py \
  tests/test_container_recovery_fixture.py \
  --basetemp=/tmp/pipeline-r4-final-stream-20261008 --tb=short
```

**140 passed, 1 skipped** in 43.92 seconds, with the existing Starlette TestClient
deprecation warning. The skipped installer socket-bind test is an existing sandbox
restriction; it was not added or loosened by this repair. This is local native/fake-engine
evidence, not an actual image lifecycle run. After the last documentation-only edit,
`test_deployment_contract.py` passed all **4 tests** in 0.43 seconds.
The existing `tests/test_owner_app.py -k recovery_revokes` CLI/lifespan regression also
passed **1 test** in 0.89 seconds, proving active owner recovery refusal, stopped recovery,
session revocation and retained application status with the current native application.

The existing complete-restore tests still preserve the exact synthetic credential key
and encrypted connections, uploads/provenance, byte-identical master/tailored PDFs,
owner login/session revocation, completed deliveries and Sheets checkpoints, and
interrupted-work review without replay. Container-tooling tests use fake engine calls;
the recovery fixture's native interruption/restore checks do not establish real-container
acceptance.

Focused Ruff passes for the four production modules and four owned test files. Strict
mypy passes for `sheets_integration.py`, `operations.py`, `pipeline_runtime.py`, and
`pipeline_management.py` (**4 source files**). `git diff --check` passes. The operational
YAML files parse and all relative local links in the four updated deployment/integration
documents resolve. Current Docker Compose options were checked against official Docker
documentation through Context7 (`/docker/docs`): service configuration/volume inheritance,
`--pull never`, interactive terminal behavior, and file overrides. No Compose execution
or engine validation is implied; see the official [Compose run reference](https://docs.docker.com/reference/cli/docker/compose/run/).

## Ownership and remaining acceptance

Owned production/configuration: `src/internship_pipeline/sheets_integration.py`,
`src/internship_pipeline/operations.py`, `deploy/pipeline_runtime.py`,
`deploy/pipeline_management.py`, `deploy/settings.yaml`, and `render.yaml`.
Owned tests: `tests/test_sheets_integration.py`, `tests/test_operations.py`,
`tests/test_management.py`, and new `tests/test_deployment_contract.py`.
Owned documentation: `docs/deployment.md`, `docs/render-deployment.md`,
`docs/t20-management.md`, `docs/t15-spreadsheet-sync.md`, and this report.

Web owns the narrow `sheets_router.py` StreamingResponse mount and HTTP regression,
coordinated against `csv_chunks()`. No storage/queue/identity/app module was edited by
this lane. R5 must independently verify the combined tree and original findings.
Actual Docker/rootless-Podman image/architecture lifecycle, stopped-volume recovery,
Render recovery capability, real hosted installation, live provider/SMTP/Sheets behavior
and release publication remain unverified. No engine start/reset/prune/build, disk cleanup,
private payload read, live provider/mail/Sheets write, commit, push or deployment occurred.
