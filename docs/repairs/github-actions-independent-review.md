# Independent review of prepared GitHub Actions candidate

October 8, 2026. **Static preparation passes review; no Actions run or image acceptance
is claimed.** Reviewed only `.github/workflows/checks.yml`,
`.github/workflows/container-images.yml` and `github-actions-candidate.md`, with the
later `pyproject.toml` packaging repair and actual package archive filenames, plus narrow
reads of their existing compiler/browser/smoke dependencies. No confirmed blocking issue
was found in the prepared changes.

The container workflow calls `./.github/workflows/checks.yml`, and both native matrix
jobs require that reusable job to succeed. The called workflow has `workflow_call` and
both backend and frontend jobs, so failure in either prevents image work. GitHub's
[reusable workflow documentation](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
confirms that this relative reference uses the caller's same commit. Checkout and image
revision metadata use the run's source context; the document correctly requires comparing
the actual run SHA with the pushed candidate rather than dispatching remote main.

Both check jobs now install the same LaTeX packages as the Dockerfile before tests run.
The Python gate includes full Ruff, strict mypy, pytest, package build and Compose
validation. The browser gate includes Svelte/build/bundle checks, default Chromium,
setup, web/security, email, Sheets and generation-policy suites; every named configuration
exists, and fixture servers use the synchronized Python environment. This addresses the
known missing compiler prerequisite and affected suite coverage at configuration level;
only the actual Linux run can prove the PDF failures are resolved.

The matrix maps native AMD64 and ARM64 runner labels to their corresponding image
platforms. Each platform tests Docker, transfers that built image to rootless Podman,
then tests recovery again. OCI export enables provenance and SBOM and traverses the
archive index to require the Docker-tested config digest before candidate upload.
Content-scoped Dockerfile inputs exclude newly generated evidence files, so capturing
evidence between builds does not itself alter the image source. Actual runner access,
capacity, Podman rootless behavior, build determinism and exporter acceptance remain
runtime gates.

Smoke capture uses explicit Bash `pipefail`, so `tee` cannot hide a failed acceptance
script. An `always()` evidence upload retains source/runner/disk/log records even when
a platform step fails, with separate platform/SHA artifact names and seven-day retention.
Candidate image upload occurs only after the digest assertion. Partial evidence or an
existing uploaded artifact must still be interpreted against the overall job result.
The smoke runner prints sanitized summaries and omits raw engine setup logs; application
volumes, credential keys and browser fixture directories are outside the uploaded paths.
Permissions remain `contents: read`, no application secrets are passed, and no registry
push/publication is configured. Build arguments contain only version/source/revision
metadata, so maximum provenance does not expose an application credential supplied by
these workflows.

Independent local validation parsed both workflow mappings with YAML's string-preserving
loader, checked the reusable dependency, permissions and exact matrix, and parsed **25
shell scripts and three embedded Python programs** without engine execution. Named Playwright
configuration paths were checked. `actionlint` is not installed, so this is not an
actionlint or GitHub-server validation result. No engine, provider, authentication API,
workflow dispatch, commit or deployment was operated by this reviewer; only public
GitHub documentation was read online.

## Actual package archive follow-up

The parent subsequently reproduced generated web files leaking into Hatch's source
distribution. Independent filename-only inspection confirms the original source archive
in `/tmp/pipeline-repaired-package-20261008` contains **2,490 entries, including 2,210
forbidden generated paths**: `.svelte-kit`, `node_modules` and several `test-results*`
directories. Four filenames are setup/session/state JSON inside those result directories.
No archived payload or credential content was read. The original wheel has 59 entries
and none of the forbidden paths.

The explicit current Hatch source-distribution exclusions cover web dependencies, Svelte
output, built assets, every `test-results*` directory and Playwright reports. The rebuilt
source archive in `/tmp/pipeline-repaired-package-clean-20261008` has **281 entries and
zero forbidden paths**; its wheel has **59 entries and zero forbidden paths**. The clean
archives also exclude `.git`, `.venv`, `__pycache__` and `web/build`, while the source
archive retains Python/web source, dependency locks, Dockerfile, Compose and workflow
files. This verifies the actual repaired artifacts, not merely the intended glob syntax.

The newly added CI archive-content program was executed against both pairs with only
its `dist` directory replaced by the respective temporary archive directory. It rejects
the original source archive at the generated/private-files assertion and accepts the
rebuilt source archive plus wheel. The only remaining completeness note is nonblocking:
its forbidden-path predicate does not independently assert the `web/build` exclusion;
Hatch excludes that path and the reviewed clean archive contains none.

Reviewed rebuilt archive SHA-256 values:

```text
b59cdc090ec4f00e5fbc448ef11cd99ba14b7d005417068972f137ac1ecded9f  internship_pipeline-0.1.0-py3-none-any.whl
86168e34049537fb49f0452136bc8e6d395486214863d5d993794b1fc7afdb71  internship_pipeline-0.1.0.tar.gz
```

Reviewed SHA-256 values:

```text
ddf82cedc9f954ca4eb4786cc85df84f7fa18c605fdaf9e7075b4e430124349d  .github/workflows/checks.yml
5fe7e47929c9d9c651a3eacafc26ab1fda4568f617f8503e83a36af76c3d6e3a  .github/workflows/container-images.yml
991e53cda1f7219acad0e275deaf8d7a09f8b7417897d992bcacd9add0934739  docs/repairs/github-actions-candidate.md
c92a321d4f791f68fa160963085a451e61bc40d493a99833e0dc2d25dbbcad47  pyproject.toml
```
