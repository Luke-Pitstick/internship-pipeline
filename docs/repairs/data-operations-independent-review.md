# R5 independent data and operations review

October 8, 2026. **B5 and O1–O4 pass independent native/synthetic review. Actual image,
Docker/Podman and Render acceptance remain unverified.** Reviewed HEAD
`3239183c8b2de4a6f3227eac9e750ddb5ce8d53c` plus the current uncommitted repairs, including
the final web-owned CSV response cleanup. This is defect-specific sign-off, not release
completion or a substitute for R5's whole-product checks.

## Defect verdicts

| Finding | Verdict | Independently verified behavior |
| --- | --- | --- |
| B5 | **PASS** | The original 10,003-row stable-ID CSV regression passes. A separate native reproduction exports **20,003 rows**, exactly matching every database ID in order, without duplication. The actual authenticated endpoint exports a real SQLite inventory over 10,000 rows. Sheets admits 10,000 local jobs, rejects 10,001 before saving a plan, refuses destination row overflow without accepting a partial plan, and refuses inventory growth past capacity at queue admission without remote writes. |
| O1 | **PASS** | Populated backup/restore regressions preserve task data and owner login for literal `?`, `#`, space and Unicode paths without creating alternate files. A separate native reproduction adds literal percent encodings and combined query/fragment/Unicode paths. Hash-valid empty, unrelated and swapped state/identity databases fail verification; wrong source databases fail before backup publication. |
| O2 | **PASS** | Fake Docker and Podman emit recognized worker lifecycle events on stderr; management preserves those events and redacts secret-looking lines from both streams. Inspection JSON remains stdout-only. Combined successful output above the inspection limit fails, and failed-engine stderr stays out of the displayed failure. |
| O3 | **PASS** | Both shipped operational Settings examples load through the real strict loader. `deploy/settings.yaml` uses the current state path and excludes the obsolete fields. Render configuration removes `CODEX_HOME`; current browser Settings, independent workers and readiness behavior are documented. |
| O4 | **PASS for native/prepared recovery contract** | Current account recovery instructions stop writers, retain the volume and pin the one-off container to the inspected image ID. The host commands use the saved endpoint and volume, literal argv, `--pull never`, `--network none`, an interactive terminal, and leave the app stopped. Running-container and noninteractive requests are refused. The real exclusive native lock refuses both commands while writers are active; stopped token rotation and owner recovery/session revocation pass. Actual engine/platform execution is not established. |

No additional confirmed production defect remains in this review scope. The initial
CSV transport-test run occurred during the web worker's deliberate red/edit phase and
found a route lookup error in that new test; the settled fixture and production code were
subsequently rerun. That transient result is not represented as a passing final check.

## Additional failure boundaries

CSV uses a dedicated escaped, read-only SQLite connection, an explicit read transaction,
stable ID order and one row per chunk at
`src/internship_pipeline/sheets_integration.py:251–322`. The retained snapshot and
sequential thread-pool-hop tests pass. The separate 20,003-row reproduction measured
**20,004 chunks, 2,760,551 encoded bytes, a largest chunk of 152 characters and a 394,506-byte
tracemalloc peak** with a constant-space consumer. This is observed bounded iteration
for the synthetic inventory, not a fixed memory ceiling for arbitrarily large individual
field values. The convenience `csv()` joins chunks; the HTTP path uses the iterator.

`csv_chunks()` explicitly closes its inner facts generator, and
`src/internship_pipeline/sheets_router.py:15–26` closes it in the response's `finally`.
Independent native ASGI calls verify actual SQLite closure on normal completion, modern
ASGI send `OSError`, and older ASGI disconnect cancellation. Closure is checked immediately
inside the coroutine, before event-loop shutdown can finalize asynchronous generators and
mask a leak. Explicit early iterator close and a Sheets-capacity exception also close
the read connection.

`operations.py:80–103,228–232` checks each database against its distinct current base
schema as well as integrity, so an integrity-valid empty or swapped file cannot pass.
The full existing native restore regression still preserves the exact synthetic key,
encrypted connections, upload provenance/files, byte-identical master/tailored PDFs,
owner authentication, revoked sessions, completed email/Sheets state, and interrupted
work requiring review. Source-preservation, fresh-destination, hash/key/symlink failure
and lock regressions also pass.

The exact account-recovery shell block in `docs/deployment.md` was run through `/bin/sh`
with a standalone temporary fake `docker` executable. Only its override filename was
replaced with a unique temporary path. Both `setup-token` and the documented
`recover-owner` substitution preserve inspected-ID interpolation, disabled networking,
no pulls, the existing Compose service, and success-only restart; simulated maintenance
failure prevents restart. No engine was contacted. Runtime output's 2 MiB check is
post-capture, not a streaming capture-memory bound. The T20 backup example remains an
operator-filled preparation example; immutable-image, actual mount permissions and
real stopped-volume backup/restore remain acceptance work.

## Commands and observed results

All pytest runs use the space-free audit interpreter, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONPATH=src`, `-p no:cacheprovider`, `--tb=short` and unique basetemps.

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /tmp/internship-pipeline-audit-venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_sheets_integration.py tests/test_operations.py tests/test_management.py \
  tests/test_deployment_contract.py tests/test_installer.py tests/test_container_smoke.py \
  tests/test_container_recovery_fixture.py \
  --basetemp=/tmp/pipeline-r5-data-operations-20261008-independent --tb=short
```

**140 passed, 1 skipped** in 41.16 seconds. The existing installer socket-bind test skips
because this sandbox denies loopback binding; it remains an environmental verification
gap. Container-tooling fixtures use mock engines/native recovery and do not prove an
actual container ran.

The settled CSV/owner subset (`tests/test_csv_stream_response.py tests/test_owner_app.py
-k 'csv or recovery_revokes'`, basetemp
`/tmp/pipeline-r5-csv-final-lifetime-20261008-independent`) passes **5 tests**, with 12
deselected, in 4.88 seconds. The final settled rerun of
`tests/test_sheets_integration.py tests/test_operations.py tests/test_management.py
tests/test_deployment_contract.py tests/test_csv_stream_response.py`, using basetemp
`/tmp/pipeline-r5-operations-final-settled-20261008-independent`, passes **101 tests**
in 28.79 seconds. Counts overlap and must not be added.

Independent temporary scripts:

- `/tmp/pipeline-r5-data-operations-native.py`: complete 20,003-row CSV, bounded consumption,
  early close/capacity-failure close, and three additional populated URI-path restores pass.
- `/tmp/pipeline-r5-csv-asgi-native.py`: normal completion, send failure and disconnect all
  close the real read connection before ASGI return.
- `/tmp/pipeline-r5-recovery-docs.py`: both documented commands pass shell execution against
  a fake engine; both simulated failures prevent restart.

`rtk git diff --check` passes. The existing Starlette TestClient deprecation warning
appears in the pytest runs; it is not a test failure.

## Tested source identity and limits

Final reviewed production SHA-256 values:

```text
47c61acd39d9fc9987bbd2f7f87b665e20377a54ef9cd86a12407a4d91be6b06  sheets_integration.py
9fa24e9a0916e66b119389fd4377e698e5e7295f5743e20fb0e5ecadf10be16e  sheets_router.py
be138f230511a1b95797c80051b6c8af404d6a1a4c51d549822509ed6d48ea2d  operations.py
8f87d69217cb02481dcef5480b9d2cabe2033090a588a4d02a9c8473fe3a76fb  deploy/pipeline_runtime.py
818b70f920afaf04470eda6af7c07f72e4d97e80739971539976672879afbea1  deploy/pipeline_management.py
```

This reviewer changed only this report and temporary synthetic scripts. Production,
tests and dependencies were read-only. No private input/environment file/credential was
read, and no provider, SMTP or remote Sheet was contacted. No image build/pull/run,
engine start/reset/prune, disk cleanup, commit, publication or deployment occurred.
Actual Docker/rootless-Podman image recovery, hosted installation, Render's exclusive
stopped-disk maintenance capability and live provider behavior remain unverified. R6–R9
and full R5 release integration remain separate gates.
