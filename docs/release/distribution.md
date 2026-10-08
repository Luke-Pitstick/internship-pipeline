# Candidate distribution

October 8, 2026. Local packaging and verification are implemented. The owner chose
MIT as the working license candidate, GHCR for images and GitHub Releases for
installer assets. This document does not certify an image, publish an endpoint or
close S4/S5. The active CI owner supplies the actual successful run, source revision,
OCI archives, platform identities and attestations before promotion. Recheck that
handoff rather than relying on older documentation that says no image exists.

## Installer artifact and trust contract

`deploy/build_installer_bundle.py` packages the five current deploy files
(`install.sh`, `install.py`, `pipeline_runtime.py`, `pipeline_management.py`,
`internship-pipeline`) **plus the root MIT `LICENSE` notice**. Nothing else enters
the archive, including hidden host configuration, fixtures, tokens, generated
session output or unrelated deploy tools. The installed command bundle also keeps
the license notice. Each input must be a nonempty regular file, not a symlink.

The archive is `internship-pipeline-installer-VERSION.tar.gz`, containing six regular
members under the matching versioned directory. File order, gzip timestamp/name,
tar timestamps/owners and permissions are fixed. Identical inputs and version under
the same Python/zlib toolchain give identical bytes; changed installer or license
bytes require a new reviewed artifact.
The builder refuses to overwrite an existing candidate. Its `.sha256` sidecar and
JSON metadata record archive length/hash and each member's length/hash. The metadata
source commit is supplied by the release operator: in a dirty working tree it is a
baseline identifier, **not proof that those bytes came from that commit**.

Build from the exact clean source revision accepted by CI, using a new output
directory and an explicit release version such as `v0.1.0-rc.1`:

```sh
python3 deploy/build_installer_bundle.py \
  --version "$PIPELINE_VERSION" --source-commit "$PIPELINE_SOURCE_SHA" \
  --output-dir "$PIPELINE_RELEASE_DIR"
```

The standalone Python 3.12+ `deploy/bootstrap_installer.py` requires an explicit
versioned HTTPS archive URL and a lowercase SHA-256 supplied from the reviewed trust
source. It never fetches or trusts a checksum automatically. It allows HTTPS CDN
redirects, refuses HTTP/credential-bearing URLs, non-200 responses, empty/oversized
or incomplete downloads, hash mismatches, malformed gzip/tar data, expanded size
overflow, duplicate/extra members, links/devices, metadata extensions, traversal
paths and a missing deploy file or license. It validates the entire archive before
writing fixed filenames into a private temporary directory, then launches
`sh install.sh` without a shell-interpolated command. Temporary downloaded files are
removed afterwards; installer-created installation data follows the installer's
retention contract. A failure before launch never calls a runtime.

For first installation, the bootstrap's `--image` must contain the reviewed
`@sha256:` OCI digest. Forwarded installer arguments cannot replace it. For a saved
installation rerun, omit `--image`; the installer requires an existing recognized
manifest and preserves its image rather than inventing a default. For stopped-source
restoration, omit `--image` and pass both full `--restore-source` and `--restore-from`
options. The installer validates the source/backup and pins its inspected local
image ID without pulling. See [installation acceptance](installation-acceptance.md).

The trust anchor is the owner-reviewed release record containing the source SHA,
archive SHA-256, bootstrap SHA-256 and accepted GHCR image digest. Fetching a checksum
beside an archive only detects transfer mistakes; it does not independently prove
who authorized the bytes. The bootstrap itself executes code, so review it from the
accepted source revision or verify its separately recorded SHA-256 before running
it. No custom signature system or unverified attestation claim is added. GitHub
release assets/tags must be treated as replaceable until the owner enables and
verifies release immutability; digest checks remain mandatory.

## Hosted command after publication

The following variables must come from the actual release handoff:
`PIPELINE_BOOTSTRAP_URL`, `PIPELINE_BOOTSTRAP_SHA256`, `PIPELINE_BUNDLE_URL`,
`PIPELINE_BUNDLE_SHA256`, `PIPELINE_VERSION`, and `PIPELINE_IMAGE_DIGEST_REF`.
The first two identify the released bootstrap; the bundle URL must end in the exact
versioned archive filename. No live installer URL is assigned by this preparation.
After publication and independent access verification, the operator can run:

```sh
set -eu
pipeline_download_dir=$(mktemp -d)
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output "$pipeline_download_dir/bootstrap_installer.py" "$PIPELINE_BOOTSTRAP_URL"
python3 - "$pipeline_download_dir/bootstrap_installer.py" "$PIPELINE_BOOTSTRAP_SHA256" <<'PY'
import hashlib, hmac, pathlib, re, sys
expected = sys.argv[2]
if not re.fullmatch(r"[0-9a-f]{64}", expected):
    raise SystemExit("A reviewed complete bootstrap SHA-256 is required")
actual = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
if not hmac.compare_digest(actual, expected):
    raise SystemExit("Bootstrap checksum mismatch; do not execute")
PY
python3 "$pipeline_download_dir/bootstrap_installer.py" \
  --bundle-url "$PIPELINE_BUNDLE_URL" --sha256 "$PIPELINE_BUNDLE_SHA256" \
  --version "$PIPELINE_VERSION" --image "$PIPELINE_IMAGE_DIGEST_REF" \
  -- --runtime docker --port 8080
```

Python/runtime setup remains an operator prerequisite; the bootstrap doesn't install
them. The final hosted command and support matrix must be tested on fresh supported
hosts against the published bytes, through readiness, owner setup and installed
management commands. A draft GitHub release is visible only to authorized repository
users and cannot prove public anonymous installation. Public repository visibility,
published prerelease asset access and GHCR package visibility each need verification.

## No-rebuild candidate promotion

These commands are preparation for a deliberate candidate publication, **not
authorization to run remote writes**. Before running them, S2/S3 technical and
redistribution gates must pass and the owner must authorize the exact candidate.
Use maintained Skopeo, Docker Buildx and the GitHub CLI. Skopeo's
[`--all --preserve-digests` contract](https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md)
copies the complete OCI index or fails if preservation is impossible. Buildx can
[combine existing registry manifests](https://docs.docker.com/reference/cli/docker/buildx/imagetools/create/)
without rebuilding. Registry authentication uses the tooling's credential store;
don't place tokens in arguments, Git or the release record.

Set the actual `PIPELINE_RUN_ID`, `PIPELINE_SOURCE_SHA`, `PIPELINE_VERSION`,
`PIPELINE_RELEASE_DIR`, `PIPELINE_AMD64_OCI`, `PIPELINE_ARM64_OCI` and
`PIPELINE_IMAGE` (the chosen lowercase `ghcr.io/luke-pitstick/internship-pipeline`
repository). The two OCI paths and their checksum/report paths must come from the
successful run's named architecture artifacts. Download each artifact with
`gh run download RUN_ID --repo Luke-Pitstick/internship-pipeline --name ARTIFACT_NAME
--dir DIRECTORY`; inspect its actual directory layout rather than guessing the
common ancestor used by Actions upload. The active workflow currently names image
artifacts using package version, architecture and source SHA; the run handoff is the
authority if the CI owner changes that interface.

First verify the run is a successful same-repository candidate at the required source
SHA. Reconcile `source-revision.txt`, both Docker/Podman reports, archive SHA-256 and
the accepted image/config/platform IDs against that run. Review the exported SBOM
and provenance and ensure the exported platform config matches the actual tested
image. A checksum generated by a failed or unrelated run is not acceptance evidence.
The source must include the final installer, license and bootstrap bytes too.

```sh
set -eu
gh api "repos/Luke-Pitstick/internship-pipeline/actions/runs/$PIPELINE_RUN_ID" \
  > "$PIPELINE_RELEASE_DIR/candidate-run.json"
python3 - "$PIPELINE_RELEASE_DIR/candidate-run.json" "$PIPELINE_SOURCE_SHA" <<'PY'
import json, re, sys
run = json.load(open(sys.argv[1]))
assert re.fullmatch(r"[0-9a-f]{40}", sys.argv[2])
assert run["repository"]["full_name"] == "Luke-Pitstick/internship-pipeline"
assert run["head_repository"]["full_name"] == "Luke-Pitstick/internship-pipeline"
assert run["head_sha"] == sys.argv[2]
assert run["status"] == "completed" and run["conclusion"] == "success"
assert run["path"].split("@", 1)[0] == ".github/workflows/container-images.yml"
PY

# Only proceed after the checksums, smoke reports and notices above have been reviewed.
skopeo inspect --raw "oci-archive:$PIPELINE_AMD64_OCI" \
  > "$PIPELINE_RELEASE_DIR/amd64-source-index.json"
skopeo inspect --raw "oci-archive:$PIPELINE_ARM64_OCI" \
  > "$PIPELINE_RELEASE_DIR/arm64-source-index.json"
skopeo copy --all --preserve-digests "oci-archive:$PIPELINE_AMD64_OCI" \
  "docker://$PIPELINE_IMAGE:$PIPELINE_VERSION-amd64"
skopeo copy --all --preserve-digests "oci-archive:$PIPELINE_ARM64_OCI" \
  "docker://$PIPELINE_IMAGE:$PIPELINE_VERSION-arm64"
skopeo inspect --raw "docker://$PIPELINE_IMAGE:$PIPELINE_VERSION-amd64" \
  > "$PIPELINE_RELEASE_DIR/amd64-registry-index.json"
skopeo inspect --raw "docker://$PIPELINE_IMAGE:$PIPELINE_VERSION-arm64" \
  > "$PIPELINE_RELEASE_DIR/arm64-registry-index.json"
cmp "$PIPELINE_RELEASE_DIR/amd64-source-index.json" \
  "$PIPELINE_RELEASE_DIR/amd64-registry-index.json"
cmp "$PIPELINE_RELEASE_DIR/arm64-source-index.json" \
  "$PIPELINE_RELEASE_DIR/arm64-registry-index.json"
pipeline_amd64_digest=$(python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$PIPELINE_RELEASE_DIR/amd64-source-index.json")
pipeline_arm64_digest=$(python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$PIPELINE_RELEASE_DIR/arm64-source-index.json")
docker buildx imagetools create --tag "$PIPELINE_IMAGE:$PIPELINE_VERSION" \
  "$PIPELINE_IMAGE@$pipeline_amd64_digest" "$PIPELINE_IMAGE@$pipeline_arm64_digest"
skopeo inspect --raw "docker://$PIPELINE_IMAGE:$PIPELINE_VERSION" \
  > "$PIPELINE_RELEASE_DIR/combined-registry-index.json"
python3 - "$PIPELINE_RELEASE_DIR" <<'PY'
import hashlib, json, pathlib, sys
directory = pathlib.Path(sys.argv[1])
sources = [json.loads((directory / (arch + "-source-index.json")).read_bytes())
           for arch in ("amd64", "arm64")]
raw = (directory / "combined-registry-index.json").read_bytes()
combined = json.loads(raw)
expected = {m["digest"]: m for source in sources for m in source["manifests"]}
actual = {m["digest"]: m for m in combined["manifests"]}
assert actual == expected, "Combined index changed or dropped platform/attestation descriptors"
assert {m.get("platform", {}).get("architecture") for m in actual.values()
        if m.get("platform", {}).get("os") == "linux"} == {"amd64", "arm64"}
(directory / "combined-image-digest.txt").write_text(
    "sha256:" + hashlib.sha256(raw).hexdigest() + "\n")
PY
```

Record the combined digest, both source/index digests, actual platform manifest/config
digests, original OCI archive hashes, CI run URL/source SHA and exact certified support
cells in `release-metadata.json`. Include the actual measurement/notice evidence;
don't fill unknown fields with guessed data. Verify source hashes against the clean
installer build, copy its reviewed `bootstrap_installer.py` and `LICENSE` into the
release directory, and record the bootstrap hash. Then prepare a draft prerelease:

```sh
gh release create "$PIPELINE_VERSION" --repo Luke-Pitstick/internship-pipeline \
  --target "$PIPELINE_SOURCE_SHA" --draft --prerelease \
  --title "Internship Pipeline $PIPELINE_VERSION" \
  --notes-file "$PIPELINE_RELEASE_DIR/release-notes.md" \
  "$PIPELINE_RELEASE_DIR/internship-pipeline-installer-$PIPELINE_VERSION.tar.gz" \
  "$PIPELINE_RELEASE_DIR/internship-pipeline-installer-$PIPELINE_VERSION.tar.gz.sha256" \
  "$PIPELINE_RELEASE_DIR/internship-pipeline-installer-$PIPELINE_VERSION.json" \
  "$PIPELINE_RELEASE_DIR/bootstrap_installer.py" \
  "$PIPELINE_RELEASE_DIR/LICENSE" "$PIPELINE_RELEASE_DIR/release-metadata.json"
```

No workflow or command here automatically publishes a general-availability release.
Record partial registry/release writes if a later command fails; don't delete or
overwrite candidate identities to hide an incomplete promotion. Public candidate
publication, immutable asset verification and S5 installation require the subsequent
owner-approved handoff and exact downloadable URLs.

## License, notices and remaining gates

The root [MIT license](../../LICENSE) uses `2026 Luke Pitstick`, matching the current
year and repository commit-author display name; that observation doesn't establish
authority over every contribution. `pyproject.toml` declares SPDX `MIT` and includes
the license file in Python distributions. The text follows the
[OSI MIT license](https://opensource.org/license/mit). Third-party dependencies retain
their own licenses and notices. Before publication the owner must confirm the
copyright identity/year, contributed source, master template, synthetic fixtures and
design-asset rights, and approve inbound contributions under the project MIT terms.

[Existing dependency metadata](../redistribution-inventory.json) covers locked local
Python/npm packages; it is not the actual image notice inventory. Review actual
Debian/TeX/font/base-image copyright/license files and embedded fonts against the CI
SBOM, preserve required notices in the distributed artifacts, and record artifact
digests and findings. The source-only six-member installer has no third-party bundled
packages, templates or assets. That boundary doesn't clear the OCI image or sdist.

[Security policy](../../SECURITY.md) proposes GitHub private vulnerability reporting.
Read-only GitHub inspection on October 8 found repository visibility `private` and a
404 from the private-reporting endpoint. A public repository, enabled reporting,
outside-account form access and maintainer notifications remain explicit gates.
No security email or response promise was invented.

Local evidence is recorded below after final bundle freeze. It covers deterministic
packaging, safe download/extraction and launcher behavior using synthetic sources and
responses. It doesn't prove hosted access, image execution, licensed image contents or
any OS/architecture/runtime support cell. Those gates remain with CI, S2/S3 and S5.

## Local verification snapshot

The distribution suite passes **57 tests** in 0.79 seconds. Scoped Ruff and strict
mypy pass for both new scripts; Python compilation, bootstrap help and repository
`git diff --check` pass. All four documented shell blocks and their embedded Python
parse, and relative links resolve. No promotion or hosted installation command was
executed. An offline Python package build produced wheel/sdist in
`/tmp/pipeline-distribution-package-20261008`; both contain the exact root notice and
the wheel declares `License-Expression: MIT` and `License-File: LICENSE`.

After the recovery worker's backup-transfer correction, both archive builds from the
same current installer/license bytes produced identical archive, checksum and JSON
metadata files. The actual archive was unpacked through the bootstrap's validation
path, its license matched the root notice, and `sh install.sh --help` from that
unpacked directory passed with both recovery options present. No engine was contacted.

| Local candidate field | Observed value |
| --- | --- |
| Version label | `v0.1.0-rc.1`, local preparation only |
| Baseline commit | `8f14e54a88d053ef6f539f1f91d2222c7952fe52`; working tree dirty, not a certified source revision |
| Archive bytes | `16077` |
| Archive SHA-256 | `44a0d886069b1b565fb677cc5bd5dccb4d1f94f45ccd1952e726d82ae8cfeb07` |
| Standalone bootstrap SHA-256 | `ed9419a1a4fbd51ca19e284f653db9635f6c9cdb86b3eff7008bc9bba12d82e6` |
| Candidate directory | `/var/folders/5g/m0r4gtb92cd65m1l48wr7sf00000gn/T/pipeline-installer-local-20261008-5mnrzq5l` |
| Independent deterministic repeat | `/var/folders/5g/m0r4gtb92cd65m1l48wr7sf00000gn/T/pipeline-installer-repeat-20261008-reav86kt` |

The local directory is an ephemeral review artifact, not a downloadable release.
Any later installer, helper, license or bootstrap change invalidates the affected
hashes and requires rebuilding/retesting before publication. Its JSON includes the
exact six member hashes for reconciliation against a final clean accepted commit.
