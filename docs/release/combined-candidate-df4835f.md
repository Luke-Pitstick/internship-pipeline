# Combined candidate acceptance — October 8, 2026

The direct [workflow-dispatch run 37838328196](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37838328196) passed all four jobs at source commit `df4835f7674007de38a45045f593c5a0b314b680`. Both downloaded platform `source-revision.txt` records match that SHA. This accepts the combined provider, installer, recovery and application source after the earlier `49ddcef` candidate, including the final README update.

## Passed gates

- Python: 866 tests passed, one warning, no skips, in 127.45 seconds. Ruff, strict mypy (56 source files), package build/content checks and Compose validation passed.
- Frontend: Svelte reported zero errors and warnings; production build and bundle measurement passed. All 35 Chromium cases passed: default 6, setup 1, web/security 25, email 1, Sheets 1 and generation policy 1.
- Native Linux amd64 and arm64: Docker and rootless Podman each passed lifecycle and fresh-volume recovery. Checks include owner authentication, health, non-root persistence, restart/signals, interrupted work, stopped backup and restoration with preserved key/PDF and delivery state.
- Both OCI candidates passed config-digest equality with their tested images, exported SBOM/provenance and uploaded successfully. No application changes or weakened assertions were necessary during this acceptance run.

| Architecture | Engine | Lifecycle and restore | Start to setup | Idle memory sample |
| --- | --- | --- | --- | --- |
| amd64 | docker | Pass | 1.779 s | 91.04MiB / 7.751GiB |
| amd64 | podman | Pass | 2.921 s | 91.94MB / 8.323GB |
| arm64 | docker | Pass | 1.731 s | 90.07MiB / 7.726GiB |
| arm64 | podman | Pass | 2.054 s | 91.12MB / 8.296GB |

[Retained reports and OCI tar checksums](ci-df4835f/) preserve the small evidence beyond Actions retention. Checksum basenames were normalized from runner paths; values are unchanged. These synthetic smoke samples are not production resource limits; full-workload memory and registry pull measurements remain separate.

## Artifact and source scope

The run contains `image-0.1.0-amd64-df4835f7674007de38a45045f593c5a0b314b680` and `image-0.1.0-arm64-df4835f7674007de38a45045f593c5a0b314b680`, retained for seven days, through October 15, 2026. This workflow does not publish registry images or installers and uses no real provider credentials, external email or remote Sheet writes.

The earlier passing [PR run 37836980879](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37836980879) reported head `a02770b` but actually built GitHub merge commit `c33da779d5bd22455933ae07efccc7bafa4d2c4e`, whose differences were previous CI evidence documents. It is supporting evidence only. This direct run supplies the unambiguous source/image identity used for the combined candidate.

This closes the combined source/browser/native-runtime gate described in [completion status](completion-status.md). It does not close bounded live-provider acceptance, distribution notices/security/publication, installation from published artifacts, declared support/accessibility, or the operating trial. Later commits require assessment of their changes before inheriting this result. The new documentation commit records these results without changing the accepted runtime source.
