# Curl installer publication

The tooling generates a release `install.sh` that embeds the exact bootstrap hash,
installer archive hash and immutable GHCR image reference. A user selects a versioned
URL and runs it through `sh`; they don't supply those hashes or an image. Python 3.12+
and a healthy supported Docker/Podman endpoint are still prerequisites. The launcher
prints setup guidance and the ready browser URL; keys are entered in browser Settings.

The repository was private and had no releases at the October 8 read-only inspection.
Anonymous installation requires publicly downloadable release assets **and** anonymous
pull access to `ghcr.io/luke-pitstick/internship-pipeline`. Creating a draft doesn't
provide either. Repository/package visibility changes and publishing the draft require
the owner's deliberate release decision; this implementation session performs none.
See [the distribution gates](distribution.md) for image license/notices review and
[curl installation acceptance](curl-installation-acceptance.md) for host evidence.

## Accepted source and candidate

Commit the final launcher, bootstrap, installer and publication code, then run
`container-images.yml` manually on the repository's default branch at that exact SHA.
Both native Linux architectures, Docker and Podman lifecycle/recovery checks and the
workflow's prerequisite checks must complete successfully. A previous successful run
cannot certify later installer changes. Review its actual SBOM/provenance, source and
redistribution notices before dispatching publication; the helper verifies artifact
bindings but doesn't decide license rights or certify macOS hosts.

The publication workflow is manually dispatched on that same accepted revision with
an explicit candidate run ID, full source SHA and version such as `v0.1.0-rc.1` matching
the package version. It accepts only successful `workflow_dispatch` runs of
`.github/workflows/container-images.yml` from this repository's default branch; fork
and PR candidates are rejected. Actions artifact names must be exactly
`image-{package-version}-{amd64|arm64}-{source-sha}`. A unique regular archive/report
file is resolved within each artifact, including Actions' common-ancestor layout;
missing, duplicate and linked files are rejected.

Before registry writes the helper verifies source revision, dependency lock bytes,
archive checksum, both tested platform/config IDs, OCI labels, each referenced blob
digest and size, and SBOM/provenance subjects. It renders and shell-parses a complete
preview installer. The source must be clean at the accepted HEAD, and required inputs
are compared directly against `git show`, so ignored files and `assume-unchanged`
edits cannot be falsely attributed to the commit. The executing bundle/launcher/asset
generators must have the exact accepted source bytes too.

## Validate locally without publishing

Use the installed GitHub CLI to download the accepted run metadata/artifacts, with
`PIPELINE_RUN_ID` containing its numeric ID and `PIPELINE_REVIEW_DIR` a fresh directory
outside the source checkout. These commands are read-only remote operations:

```sh
gh api "repos/Luke-Pitstick/internship-pipeline/actions/runs/$PIPELINE_RUN_ID" \
  > "$PIPELINE_REVIEW_DIR/run.json"
gh api --paginate --slurp \
  "repos/Luke-Pitstick/internship-pipeline/actions/runs/$PIPELINE_RUN_ID/artifacts" \
  > "$PIPELINE_REVIEW_DIR/artifacts.json"
gh run download "$PIPELINE_RUN_ID" --repo Luke-Pitstick/internship-pipeline \
  --pattern 'image-*' --dir "$PIPELINE_REVIEW_DIR/candidates"
python3 deploy/publish_release.py \
  --source-dir . --artifacts-dir "$PIPELINE_REVIEW_DIR/candidates" \
  --run-json "$PIPELINE_REVIEW_DIR/run.json" \
  --artifacts-json "$PIPELINE_REVIEW_DIR/artifacts.json" \
  --repository Luke-Pitstick/internship-pipeline --default-branch main \
  --source-commit "$PIPELINE_SOURCE_SHA" \
  --version "$PIPELINE_VERSION" --output-dir "$PIPELINE_REVIEW_DIR/release"
```

Without `--promote`, the helper makes no registry/release calls. It writes the validated
candidate report to stdout and creates `release-preview/` with `install.sh`, standalone
bootstrap, deterministic six-member bundle, bundle review JSON/checksum, root license,
`release-metadata.json` and `SHA256SUMS`. The preview uses an explicitly synthetic
zero image digest for shell validation and **must not be installed or published**.
A real asset set can also be generated offline with `build_release_assets.py` using
an explicitly accepted combined image digest; output directories must be fresh.

## Staging and public URLs

The read-only validation job has only content/action read access. Its dependent promotion
job has content and package write access, downloads the selected artifacts again and
revalidates them. Workflow inputs pass through environment variables and literal argv.
Credentials go through tooling's password stdin and are cleared afterward.

Skopeo's [`--all --preserve-digests`](https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-copy.1.md)
copies both complete OCI indexes and fails if digests can't be preserved. The helper
compares source/registry index bytes, then [Buildx imagetools](https://docs.docker.com/reference/cli/docker/buildx/imagetools/create/)
combines only those two known digest references. It compares every final platform and
attestation descriptor against the originals before pinning the combined image digest
into assets. No image rebuild happens during promotion.

The helper refuses an existing Git tag, release or version/platform registry tag;
inconclusive lookup errors fail closed. Workflow concurrency serializes publication.
The [OCI registry error contract](https://github.com/opencontainers/distribution-spec/blob/main/spec.md#error-codes)
distinguishes an absent manifest/package (`MANIFEST_UNKNOWN`/`NAME_UNKNOWN`) from denied
access; authentication and network failures never count as tag absence. A fresh GHCR
package is supported when the registry unambiguously reports its absence.
It uses [`gh release create`](https://cli.github.com/manual/gh_release_create) with
`--target` set to the accepted source SHA, `--draft --prerelease --latest=false`.
It creates no stable/latest alias. Failed promotion may leave exact versioned registry
tags or a draft; inspect and record those writes before retrying, and don't overwrite
identities to conceal a partial release. Workflow evidence is retained even on failure.
`release-publication-state.json` records attempted and verified destinations/digests,
so a command failure leaves the affected operation explicitly uncertain.

After the owner publishes the draft and establishes anonymous access, the release notes
contain the exact versioned command, shaped as
`curl -fsSL https://github.com/OWNER/REPOSITORY/releases/download/VERSION/install.sh | sh`.
The placeholder form is documentation, not an available hosted command. A prerelease
uses `/releases/download/VERSION/install.sh`; `/releases/latest/download/install.sh`
selects a latest stable release and won't select this staged prerelease. Don't advertise
the latter until a stable release with verified assets exists. Hosted HTTPS downloads,
anonymous GHCR pulls and browser readiness on a declared supported host remain final
acceptance gates after publication.

Primary CLI contracts were checked October 8, 2026 using Skopeo's manual, Docker's
Buildx reference, and GitHub CLI's [release creation](https://cli.github.com/manual/gh_release_create)
and [artifact download](https://cli.github.com/manual/gh_run_download) references.

## Local implementation evidence

On October 8 the focused asset/publication suite passed **31 tests**. It exercises
deterministic output and checksum binding, clean committed generator/input bytes,
the actual minimal GitHub run shape, nested Actions artifacts, rejected source/lock/
config/checksum mismatches, fork/PR runs, ambiguous files, blob tampering, write-free
validation, literal argv with spaced paths, exact OCI copy/index references, draft
release flags, and absent/existing/denied registry or release identities. Scoped Ruff
and strict mypy pass for both helpers; workflow YAML, every shell block and embedded
Python parse, and `git diff --check` passes. No actionlint binary was installed locally.
These are synthetic/local checks; no actual OCI candidate was downloaded, registry
write or release creation was executed, and hosted installation remains unverified.
