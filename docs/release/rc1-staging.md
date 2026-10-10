# v0.1.0-rc.1 staging — October 9, 2026

**Current status (October 10):** [RC3 acceptance](rc3-status.md) supersedes older preparation results below. RC3 is a public prerelease; anonymous Linux installation/recovery and one macOS arm64 Docker journey pass. Live, remaining host/operator and trial gates remain open. RC1 and RC2 are held drafts.

**A verified draft prerelease exists; public release acceptance is incomplete.** The draft targets `25e97fbdda2b718616d56f2f06b9f5ec5c9af338`. [Candidate run 37861200652](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37861200652) passed on the default branch; [staging run 37886214373](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37886214373) passed both validation and promotion. The [draft release](https://github.com/Luke-Pitstick/internship-pipeline/releases/tag/untagged-2ae9ba13d1d1b29fb8d7) is visible to authorized repository users. Its temporary draft URL is not the generated versioned install URL.

## Verified result

- 949 Python tests passed, one warning, in 177.44 seconds. Ruff, strict source typing, package/Compose checks, Svelte checking/build/budget and all 35 Chromium cases passed.
- Native amd64 and arm64 Docker/rootless Podman lifecycle and fresh-volume recovery passed. OCI config identities matched the tested images; source, lock, archive/blob, platform and attestation checks passed again during publication.
- GHCR platform indexes were copied with digest preservation; registry bytes matched the source indexes. The combined index retained the exact platform and attestation descriptors.
- Eight draft assets uploaded: launcher, bootstrap, installer archive, bundle review JSON, archive checksum, project license, release metadata and SHA256SUMS. Authenticated download verified all seven entries in SHA256SUMS, plus the launcher/bootstrap/bundle hashes against metadata. The actual downloaded bundle passed the bootstrap's safe extractor and its unpacked installer's help. Launcher shell syntax/help passed. No runtime installation was performed by these help checks.

Pinned image:

`ghcr.io/luke-pitstick/internship-pipeline@sha256:616d882df67a978a8b7fd798d90cb6e4634caa03a4e63ffb09cb973f9788130d`

The [release metadata](rc1-evidence/release-metadata.json), [asset checksums](rc1-evidence/SHA256SUMS) and [registry/draft write ledger](rc1-evidence/release-publication-state.json) retain the exact identities. Installer archive SHA-256: `f80065ecc64a79af323e47c7431b8da9934b75f8ce0cbbc8017d535184c9ec53`.

## Repairs made during execution

PR #4 merged the verified curl installer. [PR #5](https://github.com/Luke-Pitstick/internship-pipeline/pull/5) ships the project LICENSE and Vite-generated bundled notices, keeps uv/cache out of runtime layers, and makes missing notice files fail image construction. The first notice run exposed the Docker context allowlist omission; its corrected full run passed before merge. The earlier OCI notice inventory and its limits are in [image notice review](image-notices.md).

The first draft-staging attempt failed safely before remote writes because Docker and Podman format the same config digest differently. The publisher now canonicalizes only complete lowercase SHA-256 identities. A real-format fixture reproduced the failure before repair; 75 focused tests and real OCI archive verification passed afterward. The new full main candidate contains all five malformed-identity regressions. See [attempt history](staging-attempts.md).

## Still required

| Gate | Current state and missing input/evidence |
| --- | --- |
| Live models, grounded generation, SMTP and Sheets | No live requests/messages/Sheet writes were made in this release task. Jev is present in root `.env`; current general-model key/model/endpoint fields are empty. Private credential locations, exact model, spending ceiling, dedicated inbox and disposable Sheet are pending. Existing notification configuration was not used as a test destination. |
| Persistent operating trial and support scope | A persistent host, selected OS/runtime support scope and the planned 24-hour trial are pending. CI runtime acceptance does not certify hosted installer execution, macOS/Windows or a continuous operating trial. |
| Public availability and security reporting | Repository remains PRIVATE and release remains draft. Anonymous versioned curl download has not passed. GitHub private-reporting API returned 404. Local package-visibility inspection returned 403 because the CLI token lacks `read:packages`; GHCR visibility is not asserted. Publication, package access, outside-account security form/notification checks remain open. |
| Redistribution and source privacy | Project/frontend notice packaging is repaired. Full final-image notice/source-obligation and rights reconciliation remains open. Targeted scans found no common private-key/provider-token patterns in 323 tracked files and 727 historical blobs up to 2 MB, and no historical standard credential paths. Those bounded scans are not complete privacy or rights clearance. |
| Hosted installation and human acceptance | Download/hash/extraction/help checks passed with authenticated release access. Fresh hosted install/restore on declared hosts, an unfamiliar operator journey and real screen-reader evidence remain unverified. |

No stable/latest release was published. Keep model-derived rejections reviewable; this staging does not satisfy the separate automatic-rejection quality gate. Further source changes need their own acceptance and a new candidate identity, not replacement of these pinned bytes.
