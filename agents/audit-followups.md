# Completion-gap follow-ups

Requested October 6, 2026. Each worker uses **GPT-6.1 Sol, medium reasoning**. These are bounded repairs/verification assignments, not new feature milestones. Preserve others' edits, existing installations, private inputs and historical evaluation reports. Leave changes uncommitted. Record complete/partial/blocked status honestly with commands and evidence; do not claim a live or container check from mocked/native tests.

Dispatched workers: `/root/t02_split_integrity_medium`, `/root/t03_container_acceptance_medium`, and `/root/t05_live_evidence_medium`. T06, T10 and T11 returned their final handoffs before the last new worker launched. T06 records the one successful live Jev probe in `docs/t06-jev-decisions.md`; the T05 worker must use that evidence without repeating it.

## T02 follow-up — evaluation split integrity

**Ownership:** `evaluation/jev/evaluator.py`, `tests/test_jev_evaluation.py`, `docs/t02-jev-evaluation.md`, and a new `docs/t02-followup.md` if useful. Do not modify historical `cases.json` or `reports/`, production matching/policy, or shared planning documents.

1. Review the parent's `overlapping_model_inputs` guard and its invocation before secret access/network/output. Independently reproduce the six historical overlaps and the 28 unseen-input subset using actual serialized request bodies, not case IDs.
2. Verify changed labels, exact-comparison metadata, case IDs and dictionary ordering cannot disguise a duplicate request. Verify request truncation cannot bypass the full-corpus guard. Repair concrete defects and add targeted tests only as needed.
3. Verify a genuinely disjoint synthetic test corpus is accepted by the preflight path without any live call, and a contaminated one fails before loading credentials or writing output/usage records. Keep the default historical corpus immutable and document why it cannot be rerun as fresh held-out evidence.
4. Make the future T21 gate actionable: record dataset provenance and adjudication requirements, frozen tuning/evaluation boundaries, exact existing minimum sample/quality thresholds, and the fact that already-inspected examples are regression data. Do not invent independent human labels or claim the automatic-rejection gate passed.
5. Run focused evaluator tests and Ruff. Final handoff must separate the completed engineering fix from externally supplied representative human adjudication still required for T21.

**Limits:** offline only; no `.env`, credentials, paid evaluation, new thresholds, or automatic-rejection activation. No new dataset sweep is required to close this engineering assignment.

## T03 follow-up — actual single-container acceptance

**Ownership:** Dockerfile, compose.yaml, .dockerignore, deploy scripts, container-specific smoke tests/scripts, `docs/t03-container-owner-setup.md`, and a new `docs/t03-followup.md`. Coordinate changes to shared bootstrap/app modules with the parent; do not overwrite T06/T10/T11 work.

1. Diagnose Docker availability using bounded checks. Previous sandbox socket access was denied and an approved 15-second host-access `docker info` timed out. Distinguish sandbox access from an unavailable engine. Inspect runtime state read-only before taking action. If starting an installed desktop runtime is necessary, use its connector or Launch Services (`open -a`), never its bundle binary.
2. On a responsive engine, build the current application image. Resolve scoped packaging failures, keeping the existing single-container architecture and persistent data root. Do not install privileged software, reset/prune Docker, kill unrelated processes or touch existing volumes.
3. Start a uniquely named temporary container/volume, loopback-only port and synthetic owner. Prove built frontend and API share the published port; setup readiness works without models/profile/integrations; unauthenticated private requests fail; claim is single-use; login/logout work; real filesystem ownership permits database writes.
4. Restart the same container with the same temporary volume. Prove owner/data persist, claim stays closed and readiness recovers. Verify graceful stop/signals and retain sanitized commands/results. Clean up only resources created by this assignment.
5. If Docker remains unavailable, finish a runnable bounded smoke script and static checks, then return **blocked** with the precise required external action. Do not mark actual container acceptance passed or silently defer it to T18.

**Limits:** no deployment, publishing, paid service, real credentials, notifications, multi-architecture certification or installer work. T18 retains portability/release-image scope. Final evidence must identify host/runtime/image and each acceptance result.

## T05 follow-up — close live Jev verification evidence

**Ownership:** `docs/t05-model-configuration.md`, a new `docs/t05-followup.md` if useful, and focused `tests/test_model_connections.py` repairs only. Coordinate any necessary provider implementation change with the parent; T06 owns production assessment integration.

1. Read T06's recorded successful live probe evidence and inspect the actual production client path it exercised. T06 reported exactly one synthetic call through `ModelConnectionStore.save/reserve_test`, `providers.connections.probe`, and `complete_test`, using an isolated temporary encrypted database. Selected/resolved model was `jev-1.13.0`; usage was 480 input / 102 output tokens; persisted readiness was true. Temporary DB/key were removed and real settings were untouched.
2. Verify the implementation/tests connect configuration, reservation, probe validation, effective model identity and completed readiness correctly. Run focused model-connection tests; fix any concrete test/contract gap within scope.
3. Record that T05's Jev live-client verification gap is closed by that probe, with its narrow limits: connectivity/typed capabilities, not matching quality or auto-rejection calibration. Preserve the distinction between prior mocked evidence and this later live evidence.
4. Explicitly retain general-LLM live verification under T12/T21 because no credential was supplied; configurable run budgets under T08; full encryption-key/database restore under T17. Do not imply those were delivered by this smoke check.

**Limits:** no additional live request, credential read, `.env` access, real settings mutation, evaluation sweep or invented provider support. If T06's saved evidence is incomplete, request the handoff from the parent/T06; do not rerun the paid call merely to recreate a log. Final report must distinguish directly verified code/tests from T06-reported live results.
