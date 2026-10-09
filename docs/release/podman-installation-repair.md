# Published-image installation defect — October 9, 2026

RC1 is still a draft and must not be advertised as a working Podman installer.
The earlier container candidate tests loaded Docker archives into Podman. Actual
registry pulls exposed a different image-metadata contract.

[Run 37996030243](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37996030243)
tested installer bytes from the successful staging artifact, verified against the
same SHA-256 values as the downloaded draft assets. Docker passed fresh install,
owner claim, saved rerun, installed management, stopped backup, separate-volume
installer restore, retained encrypted connections and PDF checks on amd64 and
arm64. Podman timed out during first installation on both architectures.

[Diagnostic run 37996316343](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37996316343)
reproduced both Podman failures. The containers were running with exit code zero,
but `Config.Healthcheck` was absent and health status was empty. Docker's image
health metadata survived its pull; Podman did not retain it from the OCI image.
The installer had assumed both engines would retain this metadata.

A separate contract defect affected installer readiness and installed `status`:
Podman's native JSON uses `State.Healthcheck`, while Docker uses `State.Health`.
Earlier fake-engine fixtures incorrectly emitted Docker's field for both engines.
Correcting the Podman fixture reproduced a management startup timeout before the
repair. Podman's Go-template `.State.Health` alias had hidden the JSON distinction
in the earlier container-only smoke test.

The repair sets the health command explicitly when creating either engine's
container, shares one application readiness command with the Dockerfile, and reads
each engine's native JSON field. The command checks the local `/readyz` response
with the configured Host, without proxies or redirects, and fails closed on
connection errors, non-200 responses or unexpected payloads. Installed status and
startup use the same readiness interpretation. Engine fixtures now reflect their
actual JSON contracts.

The repair changes the installer and image. It requires a fresh candidate and
versioned release assets; RC1 bytes are not to be replaced. Local regression
results and the new full candidate/registry-installation run will be recorded when
they finish. No model, email or Sheets request was made during these checks.

The read-only staging-artifact workflow does not certify public launcher delivery.
Draft release reads required broader GitHub token permissions; automatic approval
review rejected that expansion. The accepted replacement retains only
`contents: read`, `actions: read` and `packages: read`, downloads the existing
staging artifact and requires independently recorded asset hashes before execution.
The separate `public-launcher` mode downloads without credentials.
