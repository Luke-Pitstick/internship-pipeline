# Storage format

The current application declares **storage format 2** in
`src/internship_pipeline/storage_format.py`. This identifies the persistent data
contract independently of the application version, host installation manifest
schema, and backup archive format. SQLite schema revisions are tracked separately
with `PRAGMA user_version` and upgraded by ordered transactional migrations.

## Inspecting a release

Run the read-only module from the application's Python environment:

```sh
python -m internship_pipeline.storage_format
```

It prints `{"storage_format": 2}` using only the Python standard library. It does
not read configuration, create an installation, acquire a data lock, or start
workers. The application maintenance CLI also accepts
`python -m internship_pipeline.cli storage-format`. The separately installed
host-management command exposes release eligibility through `update --check`.

Release generation executes the declaration from the verified, clean source
revision and records its value as `storage_format` in `release-metadata.json`.
It refuses absent, noninteger, or nonpositive declarations. Downloaded-release
acceptance runs the same module in the exact installed image with networking
disabled and compares its output with that source-bound metadata. Publication
therefore has an explicit check to run before claiming the image's format.

## What format 2 covers

- The jobs/state and owner/identity SQLite databases, including tables initialized
  by individual features, task payloads, and persisted status values.
- Settings and saved company/search configuration needed to reopen those records.
- The credential key, encrypted model/email/Sheets connections, and their encoding.
- ChatGPT OAuth registrations, encrypted token bundles and pending authorizations,
  stable installation host IDs, and the general model's authentication mode and
  selected registration. Format 1 readers cannot interpret these configurations;
  format 2 does not add a format fallback or conversion path.
- Retained uploads, source provenance, generated documents, and their stored paths.
- Application history and confirmed delivery/checkpoint records whose meaning must
  survive a release change without resending external actions.

Feature tables can be absent until their feature initializes them. A matching
format number is a declaration of compatible structure and meaning; it does not
replace database integrity, credential decryption, document verification, or
testing an actual source/target release pair.

## Database schema migrations

`schema_migrations.py` contains ordered migrations for each database. Existing
unversioned databases start at revision 0. State revision 1 creates `scoring_limits`
and preserves saved limits in releases that already created that table. New
installations initialize the version-zero baseline and apply the same migrations.

Add database changes as new migrations; do not edit the baseline schema or rewrite
an existing migration. Use `execute`/`executemany` for DDL and data changes.
Migration functions must not commit, use `executescript`, open another connection,
or perform external I/O. Pending migrations and the recorded version commit in
one SQLite transaction under a write lock. An exception or killed process rolls
them back, and concurrent openers cannot apply a migration twice. An image refuses
a schema version newer than its migration list.

Backups are validated against their recorded schema revision. During an update,
the target image migrates only the restored candidate databases, then checks the
real application and retained files before activation. The original databases
and verified source backup remain available for rollback. Tests include the frozen
v1.0.1 state schema, migration retry, concurrent opens, and a killed migration.

## Backups and format changes

New backup manifests record both `format: 1` (the backup envelope) and
`storage_format: 2` (the application data contract). Restore requires the storage
format to be an integer exactly matching the running image, then performs the
existing file, database, and credential verification. Missing or mismatched
declarations are refused before creating a destination. Older backups remain
recoverable through the exact older image that created them; they are not
silently relabelled as format 2.

Review every persistence change against this contract. Use schema migrations for
supported database upgrades within the same storage format. Increment the format
for unsupported changes to stored meaning, configuration, encryption, or file
layout. A format mismatch remains an explicit refusal; schema migration support
does not silently reinterpret an unrelated storage format.

The [CLI updater](cli-updates.md) uses exact source/target image declarations to
decide whether an update can proceed. Its implementation and checks are local
until release acceptance/publication. Already published images without the module
have not acquired a declaration retroactively, and editing this source does not
change an installed image or private data.
