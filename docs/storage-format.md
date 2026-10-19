# Storage format

The current application declares **storage format 2** in
`src/internship_pipeline/storage_format.py`. This identifies the persistent data
contract independently of the application version, host installation manifest
schema, and backup archive format. Declaring a format does not rewrite databases
or convert existing data.

## Inspecting a release

Run the read-only module from the application's Python environment:

```sh
python -m internship_pipeline.storage_format
```

It prints `{"storage_format": 2}` using only the Python standard library. It does
not read configuration, create an installation, acquire a data lock, or start
workers. The application maintenance CLI also accepts
`python -m internship_pipeline.cli storage-format`. The separately installed
host-management command does not yet expose this inspection command or updates.

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

## Backups and format changes

New backup manifests record both `format: 1` (the backup envelope) and
`storage_format: 2` (the application data contract). Restore requires the storage
format to be an integer exactly matching the running image, then performs the
existing file, database, and credential verification. Missing or mismatched
declarations are refused before creating a destination. Older backups remain
recoverable through the exact older image that created them; they are not
silently relabelled as format 2.

Review every persistence change against this contract. Keep the identifier when
old data can be read with the same meaning and written compatibly without
conversion. Increment it for incompatible database, stored-value, configuration,
encryption, or file-layout changes. Do not bump it for UI fixes or other changes
that leave this contract intact. Do not add a format fallback or migration.

The [CLI update plan](../agents/cli-release-update.md) will use exact source/target
image declarations to decide whether an update can proceed. This declaration is
the first prerequisite; the updater itself is still planned. Already published
images without the module have not acquired a declaration retroactively, and no
installed image or private data was changed by this source change.
