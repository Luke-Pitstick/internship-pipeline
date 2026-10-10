# RC3 acceptance — updated October 10, 2026

**RC3 is published as a prerelease. Public installation passes; full
stable-release acceptance remains incomplete.** RC3 targets
`ba21d018ae679619e22c3dfd56a816ac2a7b1e1a`. RC1 and RC2 remain held drafts, with
their original bytes retained and the Podman defects described in their notes.

## Passed

- [Expanded full CI run 38075161658](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38075161658):
  backend and frontend jobs passed at `c4664251396b73c22181fe0021d80fc9c7d97af6`,
  including all ten browser configurations (39 cases). Future CI now includes the
  four configurations that the earlier 35-case selection omitted.
- [Full source/native rerun 38074718838](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38074718838):
  Python and standard frontend checks, fresh native amd64/arm64 image builds,
  Docker and rootless Podman lifecycle/recovery, and OCI export identity checks
  all passed at `04528ea50cad9aa768a15c8cd5c82b6d75d6aee4`. This rerun did not replace
  RC3's published image or installer bytes. Reports: [amd64 Docker](rc3-evidence/fresh-native-docker-amd64.json),
  [amd64 Podman](rc3-evidence/fresh-native-podman-amd64.json),
  [arm64 Docker](rc3-evidence/fresh-native-docker-arm64.json),
  [arm64 Podman](rc3-evidence/fresh-native-podman-arm64.json).
- [Public installer run 38074717458](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38074717458):
  all four Ubuntu 24.04 amd64/arm64 Docker/rootless Podman cells passed through
  the actual anonymous versioned launcher, bootstrap, bundle and GHCR image pull.
  Fresh installation, owner claim, reruns, installed management, stopped backup,
  separate fresh restore, session revocation and encrypted settings/PDF preservation
  passed without live providers. Reports: [amd64 Docker](rc3-evidence/public-ubuntu-24.04-docker.json),
  [amd64 Podman](rc3-evidence/public-ubuntu-24.04-podman.json),
  [arm64 Docker](rc3-evidence/public-ubuntu-24.04-arm-docker.json),
  [arm64 Podman](rc3-evidence/public-ubuntu-24.04-arm-podman.json).
- macOS arm64 Docker Desktop: the published installer completed in 44.7 seconds,
  including an uncached image pull, and a rerun of the exact README curl command
  preserved the installation manifest. Installed status/stop/start returned success
  and readiness. The frontend returned 200, setup readiness returned 200, and
  anonymous jobs returned 401. A separate synthetic lifecycle/recovery run passed
  owner/login/logout, both graceful shutdown signals, same-volume persistence,
  interrupted checkpoints and fresh-volume restore with revoked sessions and no
  replay of confirmed side effects. [Sanitized report](rc3-evidence/macos-arm64-docker-recovery.json).
- Local full Python regression: 956 tests passed in 145.60 seconds, with one existing
  Starlette deprecation warning. Ruff, strict typing, Compose configuration, Svelte
  checking, production build and bundle limits passed.
- Local full browser regression: all **39 cases across all 10 configurations** passed,
  covering every browser spec file. The four previously omitted master-résumé,
  tailored-résumé, saved-search and 10,000-job workspace configurations now also run
  in CI. [Full local results](rc3-evidence/full-local-regression.json). Provider and
  delivery transports remained synthetic; temporary browser test servers stopped.
- [Candidate run 37998464922](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37998464922):
  956 Python tests, one existing deprecation warning, in 138.77 seconds; Ruff,
  strict typing, distributable/Compose checks, Svelte checking/build/budget, and
  35 browser cases. Both native architectures passed Docker and rootless Podman
  lifecycle, interrupted-work recovery and fresh-volume restore.
- [Staging run 37999393250](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37999393250):
  candidate/source/lock/archive/config identities and SBOM/provenance checks;
  digest-preserving registry promotion; eight new draft assets. Authenticated
  download verified all seven SHA256SUMS entries against the actual draft files.
- [Installer run 37999715396](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37999715396):
  all four Ubuntu 24.04 engine/architecture cells passed using installer bytes
  from the staging artifact, checked against the downloaded draft's hashes, and
  actual GHCR image pulls. The workflow retained read-only repository, Actions
  and package permissions; it did not require broader repository write access.

| Host architecture | Engine | Install through readiness | Evidence |
| --- | --- | --- | --- |
| amd64 | Docker | 29.121 seconds | [report](rc3-evidence/install-amd64-docker.json) |
| amd64 | Rootless Podman | 38.929 seconds | [report](rc3-evidence/install-amd64-podman.json) |
| arm64 | Docker | 29.868 seconds | [report](rc3-evidence/install-arm64-docker.json) |
| arm64 | Rootless Podman | 34.358 seconds | [report](rc3-evidence/install-arm64-podman.json) |

Those CI timings include the image pull and installer readiness wait, but exclude
the earlier asset download. They are observations, not consumer performance
guarantees. Each report's normalized image config digest matches the corresponding
accepted architecture in the release metadata.

The installed-command journey covered first-run claim, model deferral, retained
session across ordinary restart, idempotent installer rerun, status/start/stop/URL/
sanitized logs, stopped complete backup, a separate fresh restore, revoked source
sessions, retained owner login and one synthetic job. Image-local verification
checked encrypted model/email/Sheets settings, byte-identical retained PDF/source,
confirmed side-effect ledgers and uncertain-work review without replay. The source
remained stopped with its manifest intact, and the private host backup hashes did
not change. No live model, email or Sheets operation was made.

## Exact distribution identities

Image:
`ghcr.io/luke-pitstick/internship-pipeline@sha256:81538221a68875ceddcf7172f7918537ec4e736cd2cdd925cdb7e5c0082010ad`

Installer archive SHA-256:
`7649055ce7e08703ad1738775ec4125e7ba1da86843a681138047f091f99b76a`

[Release metadata](rc3-evidence/release-metadata.json),
[asset checksums](rc3-evidence/SHA256SUMS), and the
[publication ledger](rc3-evidence/release-publication-state.json) retain the other
identities. [amd64](rc3-evidence/notices-amd64.json) and
[arm64](rc3-evidence/notices-arm64.json) runtime inventories verify the project MIT
notice, 3,524-byte bundled frontend notices and exact installed Debian packages.
These inventories do not certify complete third-party source-obligation clearance.

The [Podman repair record](podman-installation-repair.md) preserves both failed
candidates and the observed native schema. The final runtime explicitly configures
the shared readiness command and reads the observed `State.Health` field. No
temporary product instrumentation was added or left running.

## Still open

The owner explicitly approved publication of the existing repository and history;
the repository is now public. RC3 is published as a prerelease. Anonymous downloads
of its launcher, bootstrap and installer archive passed SHA-256 verification against
the accepted identities above. Anonymous GHCR access and all four public launcher
installation/recovery cells now pass.

Enable/verify private vulnerability reporting. The successful `public-launcher`
run now certifies the normal anonymous download/bootstrap path; the older
`staged-bundle` run remains evidence for its distinct authenticated-pull path.

General-model credentials/model/budget, dedicated SMTP recipient, disposable Sheet,
persistent trial host, remaining host scenarios (including macOS Intel and Podman), unfamiliar operator, real
screen reader and the 24-hour trial are still pending. Source/asset authority and
complete redistribution reconciliation remain open. See the current
[acceptance matrix](../release-readiness.md) and [live run sheet](live-acceptance-plan.md).

Separately, a [native live Greenhouse collection](rc3-evidence/live-collection.json)
returned 424 Cloudflare postings with descriptions and no error. It did not call a
model or deliver anything, and does not certify the complete live pipeline.

Keep model-derived rejection reviewable; the independent Jev quality gate remains
unmet. Fresh installation and exact same-image restore are the current contract;
no cross-release upgrade or migration is implied.

## October 10 engine-startup reproduction

The reported "No healthy local Linux container engine" failure reproduced with a
Docker Desktop Unix socket that existed but timed out on both engine info and a
direct ping. Podman had an installed CLI but no machine or configured connection.
Starting Docker Desktop through macOS Launch Services restored Linux engine
readiness; the unchanged, hash-verified public launcher then completed successfully.
No engine detection bypass, global context change, runtime reset or data pruning
was needed. The user installation remains running and unclaimed; synthetic test
containers and volumes were cleaned up separately. The README now documents how
to verify a responding engine before retrying.
