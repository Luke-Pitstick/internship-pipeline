# One-command hosted installation

Generated October 8, 2026. Implementation starts from `fe1b71c`.

## Goal and contract

Provide a release asset `install.sh` that a user can download with curl and run through `sh`, without cloning the repository or entering an image, version or checksum. The versioned launcher binds the verified bootstrap, six-member installer bundle and exact GHCR image digest. It reuses the existing Python installer, persistent-volume ownership and readiness behavior, then prints the browser URL. The installed management command remains usable without the checkout.

Python 3.12+ and a healthy supported Docker/Podman endpoint remain explicit prerequisites. Guide missing prerequisite setup; do not silently install Python, system services or VMs. Keys belong in browser Settings and `.env.example` stays blank. Linux/macOS amd64/arm64 are candidate targets, not newly certified hosts. A public anonymous curl command additionally requires public release assets and anonymous GHCR pulls; the current private repository cannot supply that by assumption.

## Execution shape

Three GPT-6.1 Sol agents at high reasoning work with disjoint ownership. C1 and C2 implement in parallel against the interface below; C3 independently reviews and exercises the combined flow. Parent owns README, this plan, final evidence, integration and scoped commits. Critical path: launcher contract → generated release assets → end-to-end test → publishing workflow → candidate/hosted verification.

All workers read AGENTS.md, relevant release/install docs and existing tests first, preserve concurrent edits, use synthetic data and leave commits to the parent. Prefer existing Python stdlib, the bundle verifier and established GitHub/OCI tools. No custom signing framework, compatibility migration or automatic updater.

## C1 — Implement the hosted launcher

Own `deploy/release_launcher.py`, changes to `deploy/bootstrap_installer.py` only as needed, and `tests/test_release_launcher.py` / affected existing bootstrap regressions. Export `render_launcher(*, repository: str, version: str, bootstrap_sha256: str, bundle_sha256: str, image: str) -> str` for C2. The renderer validates inputs and constructs fixed versioned GitHub Release URLs, with installer bundle filename matching the current builder. The emitted POSIX shell checks prerequisites, downloads privately over HTTPS, checks the bootstrap hash before execution and passes pinned bundle metadata to the existing bootstrap. A failed/truncated download cannot start installation; options stay literal argv and no eval is permitted. Cleanup temporary files, propagate exit codes, support piped and downloaded-file invocation. Help must work without contacting Docker/Podman.

Preserve saved installation identity on rerun, including when the selected release is newer. Never turn curl rerun into an upgrade. Explicit recovery preserves its exact inspected source image. Reject ambiguous overrides rather than silently replacing image authority. Return tests for success, download/digest failure, truncated launcher, unsafe inputs, quoted paths/options and rerun behavior. Coordinate any needed installer changes with parent rather than editing another scope.

## C2 — Automate release assets and publication

Own new `deploy/build_release_assets.py`, `deploy/publish_release.py` if a helper is justified, `.github/workflows/publish-release.yml`, `tests/test_release_assets.py`, `tests/test_release_publication.py` and `docs/release/curl-publication.md`. Reuse `build_installer_bundle.py` and C1's renderer. Produce `install.sh`, standalone bootstrap, the complete installer archive, hashes and concise source/image metadata from an explicit clean source/version/image digest. Refuse overwrite and invalid identities.

Implement a manually dispatched release workflow using established GitHub CLI, Skopeo and Buildx facilities after verifying their primary docs (Context7 where available). It must select an explicit successful same-repository container candidate run, bind source SHA/workflow/artifacts and tested platform IDs, promote verified OCI bytes without rebuilding, retain dependency attestations, and assemble the multi-platform image. Validate generated assets and fail on mismatched/missing evidence before registry writes. Release tag/source must match the accepted candidate. Prefer draft/prerelease staging; do not mark any prerelease latest/stable automatically. Use least-privilege job permissions and avoid writing untrusted workflow inputs directly into shell code. Document repository/package visibility prerequisites and the distinction between latest stable and versioned prerelease URLs. Do not execute registry/release writes or change repository visibility during implementation.

## C3 — Prove the user flow and review boundaries

Own `tests/test_curl_installation.py` and `docs/release/curl-installation-acceptance.md`. Review C1/C2's planned contract immediately and send concrete findings. Reuse existing fake runtime/test helpers where practical, then execute generated shell through a pipe with controlled download transport and the real bootstrap/bundle/installer. Prove fresh setup, readiness URL, installed management after removing the source checkout, repeated installation preserving state, custom paths with spaces, missing prerequisite guidance, download/checksum failure before engine mutation and argument handling. Clearly distinguish controlled transport/fake engine tests from live HTTPS/real engine acceptance.

Perform independent security review of the final download/extraction/publication paths. Keep review read-only outside owned tests/evidence; request fixes from owners. Inspect actual public release/CI availability read-only and report the minimal remaining hosted acceptance inputs. No provider calls, emails, Sheet changes, runtime resets or publication.

## Parent integration and done criteria

Update README to lead with the intended curl flow, show a real command only when its release asset is available, and retain source development instructions separately. Record a runnable generated local candidate and clear hosted status. Run relevant full native, lint/type, shell/workflow and end-to-end checks; address review findings before scoped commits. Source changes need accepted candidate CI before publication. The engineering implementation can complete before anonymous hosting, but the public curl installation is not complete until exact hosted bytes reach browser readiness on a declared host. Surface any remaining publication/visibility decision only after preparing reviewable artifacts.

## Implementation completion evidence

C1, C2 and C3 completed their assigned implementation and independent review. Final integration passed **944 Python tests in 123.96 seconds**, full Ruff checks and strict mypy across 66 source files. The new shell-pipe journey contributes 21 tests within that total. Documentation links/fences, workflow YAML and all seven workflow shell blocks plus embedded Python parsed successfully; `git diff --check` passed. Actionlint was unavailable. Independent review left no unresolved actionable finding in this scope.

The implementation is ready for candidate CI and release review. Anonymous hosted installation remains open: the inspected repository is private, there are no release assets, and the earlier container run predates this implementation. No release, package publication or visibility change was performed. The final source needs its own successful default-branch container candidate, followed by draft staging, public-access decisions and real hosted acceptance as described in `docs/release/curl-publication.md`.
