# RC4 account setup acceptance — October 10, 2026

RC4 contains the automatic private setup-link handoff. The account form asks only for username and password; the single-use owner claim still requires local operator authority. The installer opens the link automatically, with a printed-link handoff on headless hosts. Claimed instances receive normal sign-in.

Application source: `28903c04f84fdde8976e3c0d73575a3cf13989ac`.

- [Native candidate 38076455270](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38076455270) passed **967 Python tests**, all **39 browser cases**, typing/lint/build/package/bundle/Compose checks, and native AMD64/ARM64 Docker and rootless Podman lifecycle/recovery. [Reports](onboarding-evidence/).
- [Staging 38077039698](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/38077039698) preserved the accepted OCI identities and produced the versioned installer assets. [Exact metadata](onboarding-evidence/release-metadata.json) and [checksums](onboarding-evidence/SHA256SUMS).
- The hash-verified downloaded staged installer passed on macOS ARM64 Docker: first installation, private link issuance, synthetic account claim/login/logout, rerun preservation, ordinary sign-in after claim, loopback-only binding and cleanup. [Report](onboarding-evidence/macos-staged-install.json).
- Anonymous public curl installation and the update of the existing operator instance are pending separate acceptance below.

RC3 remains immutable and retains its [historical evidence](rc3-status.md). Neither RC4 nor this onboarding fix closes live-provider, remaining host/operator, accessibility, operating-trial or redistribution gates in the [release matrix](../release-readiness.md). No automatic updater or cross-release migration has been introduced.
