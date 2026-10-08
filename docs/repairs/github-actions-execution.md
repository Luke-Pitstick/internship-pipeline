# GitHub Actions candidate execution

October 8, 2026. Owner authorized committing, pushing and dispatching the repaired candidate. Branch: `codex/release-repairs-20261008`. HTTPS OAuth lacked workflow scope; the existing configured SSH credentials successfully pushed to the same repository without changing credentials or global Git settings.

The initial candidate `0ce882f4081ed8ab99ac16799a85ab013bc37224` contains application repair commit `676de22` and the CI/package/evidence commit. Its exact SHA was verified on [run 37830607054](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37830607054).

That Linux run passed lint, strict typing, frontend check/build/bundle budget and 34 browser cases, but failed eight PDF-dependent Python tests (684 passed) and the automatic-generation browser case. Both image jobs were correctly held behind failed prerequisite checks. Installing TeX alone was insufficient: the template requires `lmodern.sty`, while `--no-install-recommends` left out the separate `lmodern` package. The dependency log lists it only as recommended. The [Debian package file list](https://packages.debian.org/bookworm/all/lmodern/filelist) identifies its TeX support files separately from `fonts-lmodern`.

Follow-up adds explicit `lmodern` to both Linux test jobs and the Dockerfile, plus `kpsewhich lmodern.sty` to fail early if the package contract breaks. Application source and test expectations are unchanged. The original 201-file manifest remains a historical record of the initial candidate; only Dockerfile/workflow entries differ after this follow-up. At this intermediate point, the R6 runtime matrix remained pending; the final accepted run below supersedes that status.

## Linux gates and Docker acceptance

At `c4b583a22e21a859443b53bb63edad7c84b36df2`, [run 37831348670](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37831348670) passed all 692 Python tests (107.14 seconds, no skips), all 35 Chromium cases, lint/types/build/package-content/Compose checks, and actual Docker lifecycle/recovery on both native architectures. Docker 28.0.4 accepted owner claim/login/logout, non-root volume writes, clean signals, restart, SIGKILL recovery without refetch, stopped backup/fresh-volume restoration, PDF/key preservation and delivery/Sheets state without replay. Both rootless Podman lanes failed while waiting for the image health check, so the overall workflow remained failed and no OCI candidate was accepted.

## Podman transfer diagnosis

Diagnostic-only [run 37832762588](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37832762588) at `cf9e95d6a64c588d62b6cfcd021292f5e6669524` repeated the successful source/browser/Docker gates and showed a running Podman container with empty health status and a failed explicit probe. A minimal BusyBox image with a `true` health check then isolated the transfer boundary in [job 113506799129](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37834150936/job/113506799129): on Podman 4.9.3, automatic `podman load` of `docker save` output produced no defined health check, whereas `podman pull docker-archive:/tmp/health.tar` of the identical archive preserved it and produced three successful automatic checks within five seconds. This distinguishes missing imported metadata from application readiness and timer failure.

The final workflow selects the explicit Docker archive transport. The health timeout and application assertions remain unchanged; no runtime health override is supplied. Temporary diagnostic job/code were removed after the reproduction, and their redundant remaining CI jobs were cancelled before the final acceptance rerun. Registry publication and installation from the exported artifact still require their own acceptance; successful Docker-archive transfer does not certify every archive/registry import format.

## Accepted candidate — October 8, 2026

[Run 37834587306](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37834587306) completed successfully at source commit `49ddcefcbd276c5c99f84650062cb48a3373f142`, pushed on `codex/release-repairs-20261008`. Both reusable source-check jobs and both native architecture jobs passed. This evidence applies to that exact commit; newer local commits and uncommitted downstream work are outside its scope. This documentation is recorded separately on `codex/ci-acceptance-evidence-20261008`, based on the accepted commit.

- Python: 692 passed, one warning, 84.96 seconds. Ruff, strict mypy across 55 source modules, package build/content checks and Compose validation passed.
- Frontend: Svelte check, production build and bundle budget passed; all 35 Chromium cases passed across default, setup, web/security, email, Sheets and generation-policy suites.
- Docker 28.0.4 and rootless Podman 4.9.3 passed actual lifecycle and recovery acceptance on both native Linux architectures, including owner authentication, health, non-root persistence, clean signals, restart, interrupted-worker recovery, stopped backup and fresh-volume restore. Restored encryption/PDF bytes and delivery/Sheets state were preserved without replay.
- Both OCI exports passed the config-digest comparison with the tested image and uploaded successfully with SBOM/provenance. No assertion or health deadline was relaxed.

| Architecture | Engine | Lifecycle and recovery | Start to setup | Idle memory sample |
| --- | --- | --- | --- | --- |
| amd64 | docker | Pass | 2.348 s | 90.26MiB / 7.752GiB |
| amd64 | podman | Pass | 3.578 s | 91.38MB / 8.324GB |
| arm64 | docker | Pass | 1.739 s | 90.11MiB / 7.726GiB |
| arm64 | podman | Pass | 2.124 s | 91.1MB / 8.296GB |

These are synthetic smoke samples, not a supported minimum-memory specification or production workload benchmark. Pull time, full-run memory and whole-container peak render memory remain unmeasured in the JSON reports.

Accepted image config identities:

- amd64: `sha256:53211685999622cce08276f0c9b499a9d0b00a38f7e3f13f72ff1df1886ca82a`.
- arm64: `sha256:7625bc871d5af30ebcbd48813b08afa0d4f949b1ef614c82a0a9adf677e4ec9e`.

The [four engine reports and two OCI tar checksums](ci-49ddcef/) retain the small evidence files beyond Actions retention. The checksum filenames were normalized from runner `/tmp` paths to portable archive basenames; checksum values are unchanged. OCI tar checksums are distinct from Actions artifact ZIP digests.

Versioned image artifacts are `image-0.1.0-amd64-49ddcefcbd276c5c99f84650062cb48a3373f142` and `image-0.1.0-arm64-49ddcefcbd276c5c99f84650062cb48a3373f142` on the linked run. Both expire October 15, 2026. The repository and artifacts are private; no registry image was published and no branch was merged.

The R6 native runtime/platform matrix is now accepted for this candidate. Broader resource/support measurements, bounded live-provider acceptance, distribution/promotion and installation from a published artifact remain separate gates. No real provider calls, external email or remote spreadsheet mutations were performed by this workflow. Newer downstream source changes require a new combined candidate before inheriting these results.
