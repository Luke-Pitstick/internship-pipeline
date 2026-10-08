# Repaired candidate — GitHub Actions preparation

October 8, 2026. The owner selected GitHub Actions for image acceptance because the local Mac has insufficient free disk space. **Prepared locally; no repaired candidate has been pushed or dispatched, and no image is certified.**

## Verified repository state

Read-only GitHub inspection found `Luke-Pitstick/internship-pipeline` is private, its default branch is `main`, and these workflows are active:

- `Offline checks`, workflow ID `375660574`.
- `Container image candidates`, workflow ID `377722909`.

The latest inspected run, [37673791568](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37673791568), failed seven PDF-generation-dependent tests (599 passed, two skipped). Those tests use the real LaTeX compiler; the workflow did not install it. The prepared test job installs the same `texlive-latex-extra` and `texlive-fonts-recommended` packages declared by the application Dockerfile. The revised workflow must run on GitHub to establish that this resolves the Linux failures; the local passing suite alone does not prove it.

## Prepared execution

The container workflow first calls the repository's offline-checks workflow at the same revision. Python tests, full Ruff, strict mypy, package build and archive-content checks, Compose validation, Svelte checking/build/bundle measurement, default Chromium, fresh setup, email, Sheets, generation policy, and the new web/security regression suite must all pass before image jobs start. Both test jobs install the TeX packages required for actual PDF verification.

The image matrix uses native `ubuntu-24.04` (`linux/amd64`) and `ubuntu-24.04-arm` (`linux/arm64`) runners. Each builds a local image, runs Docker lifecycle/recovery acceptance, loads the same image into rootless Podman and repeats acceptance, exports an OCI candidate with provenance/SBOM, then verifies that its config digest matches the Docker-tested image. Successful candidates include dependency locks and checksums. Source SHA, runner identity, disk availability, and smoke stdout/stderr are retained in a separate evidence artifact even on failure. A failed job cannot produce an accepted candidate merely because a partial artifact exists.

The workflow retains `contents: read`, uses synthetic application data, receives no application credentials and has no registry publication step. Current GitHub documentation lists both runner labels for private repositories; they consume the account's included minutes and then applicable billed usage. Artifact availability and capacity are established by the actual run, not by local YAML validation. See [GitHub-hosted runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-private-repositories).

## Dispatch the exact reviewed candidate

The repair dispatch explicitly excluded commits and pushes. Before execution, obtain authorization to commit/push the reviewed repair snapshot and dispatch CI. Use a dedicated `codex/` branch, preserve any unrelated concurrent changes, and record its full commit SHA. A run of current remote `main` would not test these local repairs.

After that branch exists remotely, dispatch using its actual name:

```sh
rtk proxy npx -y gh-axi workflow run container-images.yml --ref <reviewed-repair-branch>
rtk proxy npx -y gh-axi run list --limit 5
rtk proxy npx -y gh-axi run view <new-run-id>
```

Verify the run's source SHA equals the pushed candidate SHA, both platform jobs pass all Docker/Podman recovery steps, and the exported OCI digest check passes. Retain the run URL, per-platform reports, image/config identities, OCI checksums and attestations. Investigate failures without bypassing required checks. Promotion, live provider/SMTP/Sheets acceptance, license decisions and hosted installation remain separate release gates.

Local validation performed: both workflow files parse as YAML; all embedded shell and Python parse; reusable-workflow dependency, native platform matrix and read-only permissions are verified. This is preparation evidence only.
