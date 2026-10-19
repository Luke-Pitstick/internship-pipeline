# Update an installed app to the latest release

Generated: 2026-10-19
Source prompt: “can you plan for that feature support”
Status: proposed implementation brief; no updater has been implemented or published.

## Narrow Scope

Add an explicit `internship-pipeline update` workflow that installs the latest complete published preview on the saved engine, preserves application data, and can recover a failed update without running the new image against the original data volume.

## Grand-Scheme Fit

- User value: receive released fixes through one terminal command while retaining the profile, credentials, jobs, documents, and application history.
- App area: host management, release distribution, offline backup/recovery, and release acceptance.
- Strategic fit: extend the existing digest-pinned installer rather than introduce another package manager or background updater.
- Non-goal: database migrations, arbitrary older-development-snapshot support, or unattended updates.

## Current Context

- `deploy/pipeline_management.py` defines installed lifecycle commands and currently has no update command.
- `install.sh` selects the first complete non-draft `v…-rc.…` release from a bounded GitHub listing, then verifies repository, source, image digest, and launcher hash.
- `deploy/bootstrap_installer.py`, `deploy/build_installer_bundle.py`, and `deploy/release_launcher.py` download, verify, package, and invoke a versioned installer with fixed archive members.
- `deploy/install.py` preserves an existing manifest, command bundle, runtime, image, and volume. Its provisioning path combines resource creation and starting the app; update preparation needs a separate staging operation.
- `deploy/pipeline_runtime.py` validates exact installation ownership, resource names, image, storage, origin, and engine endpoint. Manifest schema 1 fixes container/volume names and permits two data roots; update generations require a deliberate resource-name contract change.
- `src/internship_pipeline/operations.py` verifies both databases, credential decryption, document hashes, and stopped-instance backup/recovery. Its base-schema checks permit missing optional feature tables and are insufficient to establish cross-release data compatibility.
- `docs/implementation-plan.md` directs current product work to `OPEN_SOURCE_PLAN.md`. `docs/installation-manifest.md`, `docs/t19-installer.md`, `docs/t20-management.md`, and release docs explicitly exclude updates today.
- Existing tests cover simulated engines, installation interruption, lifecycle ownership, archive safety, publication, and native backup/restore. Actual Docker/Podman acceptance remains a separate gate.
- The working tree already contains related installer, management, and account-recovery edits. Reconcile with those edits; do not overwrite or include them incidentally.

## Product Contract and Assumptions

1. `internship-pipeline update --check` reports installed and available release identities, eligibility, and why an update is blocked. It does not stop the app, pull images, or modify application data. `--json` returns bounded structured output, with an `update_available` boolean; exit zero means a successful check, including “already current.”
2. `internship-pipeline update` explicitly authorizes the update and brief downtime. Report the target version and stages without a second interactive confirmation. Resolve the target once and pin all subsequent work to its metadata and image digest.
3. Follow the existing preview channel and selection order. Do not add channels, automatic scheduling, arbitrary image URLs, downgrade flags, or an older-release fallback. If the latest complete release is incompatible, report that release and the reason instead of silently choosing another.
4. The first supported release pair must have the same declared data contract. This covers both databases, all feature-owned tables, configuration, credential encryption, and document layout. Introduce a central data-contract identifier owned by the application; every incompatible persistence change must change it. Exercise real backup validation too; matching identifiers alone are not proof of readable data.
5. Require source and target images to explicitly declare that contract. Existing images without it remain unsupported; do not infer compatibility from a version string or add migrations. A contract mismatch is refused before stopping the application.
6. Preserve the saved engine executable/endpoint, installation UUID, command location, origin, and port. Support both ordinary and previously restored installations. A running app returns to running; an app that was stopped remains stopped after offline verification and commit.
7. Updates preserve owner access, candidate facts, encrypted connections/key, searches, jobs, generated files, confirmed delivery checkpoints, and application status. Reuse recovery's session revocation and uncertain-work handling: users may need to sign in again; interrupted external actions require review rather than replay.
8. A published updater cannot add a command to an already installed old management bundle. Provide a one-time public installer invocation with `--update` to bootstrap the verified new updater against a recognized installation. Normal installer reruns retain their current meaning. Bootstrapping installs no compatibility parser and does not bypass the source-image contract check in item 5.

## Technical Implementation Plan

Implement in dependency order. Each increment must leave existing install/start/stop/recovery behavior working. Keep update unavailable until the complete transaction is accepted.

### 1. Establish release identity and data-contract evidence

- Add a small application-owned contract/version inspection command that is offline, read-only, and does not initialize databases or workers. Include the same contract identifier in source-bound release metadata and the built image; compare metadata with the inspected pinned image, not a movable tag.
- Persist a private release receipt alongside the installation manifest for version, source SHA, registry digest, and data-contract identity. Existing recognized installations may be identified by their inspected exact image, but missing data-contract evidence is a refusal, not a heuristic.
- Extract one bounded release resolver for fresh installation and updates. Preserve current preview selection and HTTPS/hash/archive checks. Give metadata one current strict schema; do not maintain old metadata parsers. Add required assets/contract fields to publication gates so incomplete releases cannot be selected.
- Plan rollout in two releases: a baseline release containing the data-contract declaration, followed by a separately published updater-capable target. Old installations without the baseline contract still require a fresh installation. Do not advertise upgrades from those older snapshots.

### 2. Prepare a verified target without downtime

- Add a host update module with a narrow `check`/`apply` boundary. Reuse runtime inspection, bounded subprocesses, existing download validation, and terminal presentation helpers.
- Download the exact target management bundle into a private staging directory, verify its declared hashes and fixed archive members, and pull the target digest through the saved engine. Include all new updater/resolver files in bundle allowlists, size bounds, tests, and release assets.
- Inspect the source image's exact local identity and retain it for recovery. Ensure the target supports the host architecture and the same data contract. Check temporary and volume capacity conservatively; actual backup/restore failures remain fatal even after an estimate passes.
- If the target digest already matches the installed image and receipt, return an idempotent “already current” result. Missing or inconsistent identity evidence must produce a diagnostic, not a false success.

### 3. Serialize lifecycle work and take a verified snapshot

- Use one installation-level lock for install, update, start, stop, owner recovery, and other host mutations. Read-only status can expose a sanitized in-progress state. Keep the existing application offline lock to exclude separately launched writers.
- Record a private update journal before the first mutation, containing transaction UUID, previous running state, source/target identities, previous manifest and bundle, staged resource identities, and a monotonic phase. Persist files atomically with file/directory synchronization; never source journal data as shell code.
- Stop the app and verify that supported writers have stopped. Use the source's exact local image with networking disabled to produce and validate a complete private backup. No confirmed backup means no cutover.
- Retain the backup and original volume. Never delete the only usable snapshot, original image, or original command bundle during the transaction.

### 4. Restore and verify a candidate on separate storage

- Create a new installation-labelled volume with a transaction-derived name, then use the exact source image's established restore path to populate `/var/data/restored`. Use the target image only after source restore succeeds and the contract matches.
- Extend the single manifest/resource validator to accept tightly specified transaction-derived names while retaining UUID labels and exact mount/image/port checks. Do not allow arbitrary resources or adopt unlabelled volumes. Keep the manifest's existing field structure; no legacy-format adapter is needed.
- Perform target verification offline against the candidate data: SQLite integrity and all current feature schemas, credential decryption, configuration, and retained file hashes. The target must never mount the original volume writable.
- Add a narrowly scoped update-validation startup mode that exposes readiness only to loopback and excludes interactive writes, collection, inference, notifications, and external delivery. Verify the candidate on the saved port after the source stops. Gate this mode locally; do not add an unauthenticated HTTP “activate” endpoint.
- No candidate background work or user writes may occur before commit. This avoids restoring a snapshot after the new version has sent an email, consumed model budget, or accepted new user work.

### 5. Commit the image, data volume, and command bundle together

- Stage an immutable target command directory. Keep the existing public command path stable, using an atomic symlink replacement to select a complete verified bundle; never overwrite imported management modules file by file.
- Update the active manifest, release receipt, and command pointer under the transaction journal. These separate filesystem writes are not one atomic operation: the journal must identify the intended generation and allow deterministic completion or restoration after every interruption point.
- Require updater-capable lifecycle entry points and the public bootstrap path to inspect an incomplete journal before touching resources. A new command must not operate a partly switched manifest/bundle combination. Recovery must remain possible when the ordinary command symlink is missing.
- After candidate readiness and durable commit, exit validation mode and start the ordinary target container only if the source was running. Keep the same origin/port. Mark activation before any normal worker/user writes are allowed.
- Before activation, any failed pull, backup, restore, validation, startup, or commit restores the previous manifest/command and restarts the untouched original volume/image if it was running. Retain failed candidate resources for diagnosis. If recovery cannot complete, return nonzero with the transaction identity and precise retry instruction.
- After activation may have allowed writes or external effects, never automatically switch back to stale source data. A later readiness/start failure is an explicit recovery state against the current candidate data, with source and backup retained. Report “committed; start/recovery required,” not “rolled back.”
- `update` on an interrupted transaction resolves that recorded transaction before discovering another target. Do not repeat an uncertain restore into an existing destination or clear markers to force progress. Preserve uncertainty and give a bounded recovery path.
- Show success only after verifying active manifest, bundle, receipt, image, data volume, and requested running/stopped state agree. Retain the previous generation and backup; automated pruning is outside this feature.

### 6. Expose the CLI and accept a real release pair

- Add `update`, `update --check`, existing `--install-dir`, and `--json` support to installed management. Separate useful plain output from structured output; keep private engine stderr and candidate facts out of diagnostics.
- Add explicit `--update` handling to the public verified launcher/bootstrap path. It must invoke the same transaction implementation without going through ordinary preserve-existing installation provisioning.
- Update help, README, installation/management contracts, and release documentation together. Describe downtime, disk requirements, retained recovery material, reauthentication, supported source releases, and schema-change refusal plainly.
- Extend candidate acceptance and publication with source-baseline → target update tests against exact published artifacts. Publish support only for runtime/architecture cells that actually pass.

## Delegate Agent Instructions

Owned scope: host updater/resolver modules; installer, management, runtime, and release asset integration; application data-contract inspection and validation startup mode; focused tests, publication checks, and associated docs.

1. You are not alone in the codebase. Preserve concurrent installer/account changes and adapt this plan to their final interfaces.
2. Follow the ordered plan and current product source of truth. This brief authorizes planning only; implementation follows a separate user request.
3. Reuse established backup/restore validation without weakening ownership, credentials, archive, or saved-engine protections. Keep collection independent of inference and notification delivery.
4. Use synthetic candidate data exclusively in fixtures and release acceptance. Do not exercise live providers or send notifications during updater validation.
5. Add only modules needed for this transaction. No migration framework, generic deployment engine, extra service, or database.
6. Record completion evidence when each implementation gate passes. Do not commit, push, publish, or mutate an installed application from this planning request.

## Acceptance Criteria

- [ ] `update --check` identifies the latest complete preview and eligibility without stopping the app or changing application data.
- [ ] A supported baseline → target update preserves representative profile/job/document/credential/application/delivery records and maintains origin, port, engine, and installation identity.
- [ ] The original volume is never writable from the target image before or after the switch; the target operates its candidate copy.
- [ ] A stopped installation stays stopped; a running installation returns ready. Session revocation is documented and owner credentials still work.
- [ ] Missing/mismatched data contracts, malformed metadata, bad hashes, foreign resources, and missing original data fail safely with a concrete reason.
- [ ] Pre-activation failures restore the original complete installation; post-activation failures never silently discard new writes or replay external actions.
- [ ] Process termination at each durable phase has a deterministic recoverable result, including interrupted command-pointer/manifest replacement and uncertain restore completion.
- [ ] Repeated/concurrent update and lifecycle commands cannot create competing writers, duplicate restores, or a mixed active generation.
- [ ] Normal installer reruns still preserve their selected release. Old command bundles can enter the new updater through explicit public bootstrap, subject to the same source-contract requirement.
- [ ] Publication accepts a real source/target pair on each claimed engine/architecture and reports the exact release identities tested.

## Validation Plan

- Automated prior art: `tests/test_management.py`, `tests/test_installer.py`, `tests/test_operations.py`, `tests/test_current_installer.py`, `tests/test_installer_distribution.py`, `tests/test_release_launcher.py`, `tests/test_release_assets.py`, and `tests/test_release_publication.py`. Add focused updater behavior and transaction interruption tests.
- Exercise running/stopped and ordinary/restored installations; same release; no complete release; missing contract; incompatible latest release; GitHub/network/hash/pull failures; insufficient storage; failed backup/restore; candidate corruption; readiness timeout; command switch failure; activation interruption; failed rollback; retry; concurrent commands; and changed global Docker/Podman settings.
- Assert durable user facts, byte/hash invariants, exact resource ownership, process/worker admission, and recovery outcomes. Use recorded provider/delivery transports to prove no side effects before activation, rather than tests that mirror private helper calls.
- Run targeted pytest through `rtk proxy` with `PYTHONPATH=src`, scoped Ruff/mypy, shell syntax, and whitespace checks. Use the repository's configured tool invocation rather than adding new dependencies.
- Real acceptance: extend `deploy/release-install-smoke.py`, `.github/workflows/release-installation.yml`, and `.github/workflows/publish-release.yml` for a published baseline → target pair, owner sign-in, retained documents/connections, update failure recovery, checkout-independent commands, and repeated update. Keep synthetic and actual-engine evidence separate.
- Review gate: review ownership/download boundaries, transaction crash recovery, and worker activation ordering before enabling the command in a published bundle. No tests or runtime acceptance were performed for this planning-only artifact.

## Out of Scope

- Database/configuration migrations and support for older snapshots without declared contract evidence.
- Automatic/background updates, browser update banners, release-channel settings, arbitrary target selection, downgrade commands, and post-use rollback that discards new data.
- Engine/host transfer, manual Compose installation updates, arbitrary image registries, and generic schema compatibility layers.
- Automatic deletion of retained images, backups, source volumes, or failed candidate volumes.

## Follow-Up Task Ideas

- Explicit inspection and owner-requested cleanup of retained generations after successful updates.
- Browser visibility of release identity, reusing the host receipt without granting browser-side update authority.
