# Updating a local installation

The host command implements explicit updates to the latest complete published
release when both images declare the same [storage format](storage-format.md).
Database schema upgrades run transactionally on an isolated restored copy.
There is no background updater. The public installer follows
only complete published releases; draft assets are unavailable to normal updates.

Stable releases and numbered release candidates use publication order. This allows
the October 2026 numbering reset from `1.0.x` to `0.1.x`; `v0.1.4` contains newer
code than `v1.0.3`. Updates verify through GitHub's commit ancestry API that the
target source descends from the installed source, and refuse older, divergent or
unverifiable code before downtime. A same-source promotion needs no comparison
request and still installs the selected command bundle and release identity.

```sh
internship-pipeline update --check
internship-pipeline update
```

`--check` reports installed and available identities, format eligibility, and a
reason when blocked. It does not stop the app, pull a target image, or change
application data. `--json` produces structured stdout; update progress stays on
stderr. Both commands accept the usual `--install-dir PATH`.

When moving from the old `1.0.x` numbering, or if the installed command predates
`update`, use the current bootstrap once to load the new release-selection policy:

```sh
curl -fsSL https://raw.githubusercontent.com/Luke-Pitstick/internship-pipeline/main/install.sh | sh -s -- --update
```

Normal installer reruns preserve the selected image. Updates retain the saved
engine endpoint, UUID, command location, origin, and port. A running app returns
to running; a stopped app remains stopped. Repeated updates to the active release
are a no-op. Already published images without a storage declaration are refused;
their format is not inferred or relabelled.

## What happens to your data

Downloads, archive/hash verification, the target image pull, and storage-format
checks happen before downtime. The updater then stops the app and uses the exact
source image to create a verified backup in a separate labelled volume. It restores
that backup into a fresh data root and verifies the new image against the copy.
The offline preflight verifies the snapshot at its recorded database revisions,
applies the target image's pending schema migrations to the restored copy, and
constructs the real app and checks its readiness route
in-process without running its lifespan or supervisor, then rechecks retained files.
The target image never opens the original data volume writable.

The validation container serves readiness only: application pages, interactive
writes, collection, model inference, and delivery are unavailable until cutover.
After verification, the updater selects a complete management bundle, manifest,
and release receipt, then permits normal work. Owner credentials survive; restored
browser sessions are revoked, so sign in again. Interrupted external actions remain
marked for review rather than being replayed.

The original data volume, pinned image, manifest, copied backup, and previous
command bundle are retained. After the activation boundary, the old app container
is retired so a host restart cannot launch two independent copies. Allow space
for both a backup and restored copy in addition to retained
original storage. A conservative free-space check runs before downtime, but a
later storage failure still stops the update safely. Updates never prune old
images, volumes, or backups automatically.

## Failure and interruption recovery

Run `internship-pipeline update` again to recover an interrupted transaction before
selecting another release. If the ordinary command pointer is missing, use the
explicit public bootstrap above. Do not edit the manifest, clear journal phases,
delete restore markers, or rerun a restore into an uncertain destination.

- Before activation, a failed update restores the original manifest/command and
  its previous running state. For a previously running app, recovery waits for
  readiness before declaring success. The uncertain candidate copy is retained.
- Once normal work may have started, recovery keeps the candidate data and finishes
  activation. It never switches back to a snapshot that could discard new work or
  repeat a notification/model request.
- An invalid journal, missing owned source resources, or damaged command bundle
  fails closed. Preserve the installation root and both volumes for explicit
  recovery; repeated attempts cannot reconstruct deleted source bytes.

Host lifecycle commands and installer reruns share `.installer.lock` and refuse
overlap. An incomplete `update.json` blocks ordinary lifecycle actions until the
update is recovered. Transaction records live in `updates/TRANSACTION_UUID/`;
the active `command` pointer selects an immutable bundle there after cutover.
`release.json` records the selected version, source SHA, image digest, and format.
Failed transactions retain `failure.json` with the failed phase and error.
Failed engine commands also retain their exit code and bounded stdout/stderr in
that private file (mode 0600). The terminal shows the diagnostic path without
printing raw engine output, which may contain private application details.

Copy and preflight processes run in named, installation-labelled maintenance
containers. Recovery verifies their image, mounts, and container identity and stops
any survivor before restarting the original app; a killed host CLI cannot leave a
copy process holding its data locks indefinitely.

## Verification boundary

Native tests verify backup/restored-copy integrity and the readiness-only handler.
They also exercise actual app initialization and reject a missing frontend without
contacting external transports.
Schema tests cover the historical v1.0.1 database, existing scoring settings,
transaction rollback, process death during migration, concurrent openers, and
refusal to open a newer unsupported schema.
Synthetic engine tests cover running/stopped installations, repeated updates,
successive generations, rollback, interrupted command/manifest changes, activation
recovery, saved-engine ownership, and lifecycle locking.

Local Docker Desktop ARM64 acceptance also exercised distinct real images from
the earlier storage-compatible `96832b9` revision and the v1.0.0 working source.
Running/stopped updates, validation-failure rollback, interruption recovery,
retained documents and encrypted credentials, owner login, and repeat no-ops passed.
That test staged hash-checked assets locally and used exact cached image IDs;
public downloads and registry pulls require the separate publication checks.

The downloaded-release workflow additionally exercises actual Docker/Podman
copy/cutover using the candidate's local config ID and registry digest, then checks
owner login, retained documents/connections, original storage, and the installed
command. Those references name the same image bytes; the report explicitly records
`cross_release_update: false`. A distinct published source/target release pair
requires its own acceptance evidence. Consult the release's Actions run for the
accepted runtime/architecture results.
