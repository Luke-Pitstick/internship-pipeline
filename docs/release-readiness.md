# Release readiness

Updated October 10, 2026. **RC3 is a public prerelease with passing public installation; stable-release acceptance remains incomplete.** The accepted application source is `ba21d018ae679619e22c3dfd56a816ac2a7b1e1a`. Current evidence is in [RC3 status](release/rc3-status.md); historical task completion is not a substitute for these release checks.

## Verified candidate

[Candidate run 37998464922](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37998464922) passed 956 Python tests, Ruff, strict source typing, package/Compose checks, Svelte checking/build/budget and all 35 browser cases. Native Docker and rootless Podman lifecycle, interrupted-work recovery and fresh-volume restore passed on amd64 and arm64. Exported image identities, SBOM and provenance passed the publisher's checks.

[Staging run 37999393250](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37999393250) preserved the accepted OCI identities in GHCR and created RC3's draft assets. Authenticated download verified all seven SHA256SUMS entries. [Metadata](release/rc3-evidence/release-metadata.json) and the [publication ledger](release/rc3-evidence/release-publication-state.json) retain the exact source and image identities.

RC1 and RC2 are held drafts. Real registry installation exposed missing Podman image health metadata, followed by an incorrect health-field assumption in the first repair. The final repair explicitly configures the health command and uses the field observed in actual runtime output. See [reproduction and repair](release/podman-installation-repair.md). Neither held draft is an accepted installer.

[Expanded full CI run 38075161658](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38075161658) passed the backend checks and all 39 browser cases across ten configurations. [Fresh native rerun 38074718838](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38074718838) also passed both architecture builds, Docker/rootless Podman lifecycle and recovery, and OCI export identity checks. These verification runs did not replace RC3's published bytes.

## Remaining acceptance

| Boundary | Current result | What closes it |
| --- | --- | --- |
| Registry installer and installed recovery | Passed all four Ubuntu 24.04 amd64/arm64 Docker/rootless Podman cells in [run 37999715396](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37999715396), including installed management, backup, fresh restore and revoked sessions. | This bounded authenticated-pull/staging-bundle gate passed. Public download, remaining host scenarios and human acceptance remain separate. |
| Public repository | PUBLIC after explicit owner approval of the existing history. | This gate passed. |
| Public image and versioned launcher | All four anonymous Linux installation/recovery cells passed in [run 38074717458](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38074717458). The README curl command also passed on macOS arm64 Docker. | This bounded public-download gate passed. |
| Private vulnerability reporting | The repository is public; private reporting and outside-account delivery still need verification. | Enable after approved public visibility, check the outside-account form and maintainer notification. |
| Live models and grounded generation | Jev's historical capability probe is documented in T05/T06. At the October 9 inspection, root `.env` general-model key/model/endpoint fields were empty; current release matching/generation uses synthetic transports in tests. | Private credentials, chosen model and bounded spending/request authorization, then the [live acceptance run sheet](release/live-acceptance-plan.md). |
| SMTP and Google Sheets | Synthetic integration and replay/recovery checks pass. No live message or Sheet mutation was performed here. | A dedicated recipient, SMTP credentials, disposable Sheet/service account and the run sheet's explicit delivery/write envelope. |
| Public ATS collection | One native live Greenhouse/Cloudflare collection returned 424 postings with descriptions, complete and without error. It did not run models or delivery. | The [record](release/rc3-evidence/live-collection.json) certifies that bounded client check only; it does not validate every source or the full live pipeline. |
| Host support and human acceptance | Native Linux amd64/arm64 and one macOS arm64 Docker installation/lifecycle/recovery journey passed. Other macOS cells, unfamiliar-operator installation/recovery and real screen-reader acceptance remain unverified. | Execute the remaining [host/operator matrix](release/installation-acceptance.md), or explicitly approve a narrower prerelease scope. Windows was not an initial target. |
| Operating trial and resources | CI measured setup/idle and synthetic PDF work. No continuous 24-hour deployment or full live-run resource envelope was observed. | A persistent approved host, declared support scope and the planned operating trial. |
| Redistribution and source privacy | Project/frontend notices were verified in pulled images. Earlier system notice inventory and exact dependency metadata are retained. A bounded history scan found no common credential/private-key patterns in 752 blobs, with no large blobs skipped. | Complete source/asset authority and corresponding-source/notice reconciliation; the bounded scan is not an exhaustive privacy or rights clearance. |

Automatic model-derived rejection remains reviewable. The separate independent Jev quality gate is unmet; do not turn rejection automation on because a connection or installer test passed. See [T02 follow-up](t02-followup.md).

## Scope of the first release

The installer contract is fresh installation and complete **same-image** backup/restore. It preserves the saved image, runtime, port and data on reruns. There is no automatic updater, cross-release migration, downgrade or cross-engine restore promise. RC3 does not make live-provider, untested macOS runtime/architecture, screen-reader or operating-trial claims.

Implementation and preparation history: [combined repairs](repairs/combined-verification.md), [prior downstream status](release/completion-status.md), [RC1 staging](release/rc1-staging.md), [live run sheet](release/live-acceptance-plan.md), [distribution](release/distribution.md), [host acceptance](release/installation-acceptance.md), and [redistribution review](redistribution-review.md).
