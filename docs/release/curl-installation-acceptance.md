# Curl installation acceptance

October 8, 2026. The generated launcher works through a real POSIX shell pipe against controlled download responses and an executable fake container runtime. Anonymous hosted installation and a real browser/container journey remain open; no publication, visibility changes, provider calls, emails or Sheet writes occurred.

## Executed user journey

`tests/test_curl_installation.py` builds the actual six-member archive, renders the actual release shell and supplies it on stdin to `/bin/sh -s --`. Its transport executables return local synthetic bytes at fixed versioned GitHub URLs. The real bootstrap performs size/hash verification and extraction, and the real installer creates its private manifest and installed management helpers. Python prerequisites and loopback port checks use the actual interpreter/socket. Only HTTPS transport and Docker responses are fake; the tests do not establish HTTPS availability, image execution or browser onboarding.

The 21 pipe cases prove:

- A fresh installation pulls and creates the pinned image, publishes only the chosen loopback port, prints its readiness URL and owner setup/log guidance, and creates a mode `0600` manifest. Readiness comes from the fake runtime's healthy state.
- The installed `status`, `stop`, `start` and `url` commands work after removing the synthetic source checkout. A second launcher carrying a newer version and a different digest preserves the original manifest, image, container identity, volume and synthetic payload, without another pull/create/restore operation.
- Paths with spaces and shell punctuation remain literal arguments. A launcher truncated halfway or immediately before its final compound-command delimiter fails without contacting the engine.
- Failed, altered and incomplete bootstrap or bundle downloads fail before any engine invocation or installation directory creation; the launcher's temporary directory is removed.
- Explicit image/default-image overrides, equals forms and abbreviated variants cannot replace the release's image authority.
- Offline help and missing Docker, Python, curl or supported Python-version guidance work without engine mutation. Missing download prerequisites make no download request.
- A bundle whose updated checksum is valid still fails before engine invocation when it contains traversal, a symbolic link or an unexpected member. Integrity verification cannot bypass extraction constraints.

No existing installation, volume or user data is used. Every file, engine record and removed checkout belongs to an isolated pytest directory.

## Commands and results

The focused run used `/tmp/internship-pipeline-audit-venv`, `PYTHONPATH=src` and an independent basetemp. Shell execution was approved outside the restrictive sandbox solely to allow the real loopback bind; download and engine boundaries remained fake.

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/pytest \
  tests/test_curl_installation.py tests/test_release_launcher.py \
  tests/test_installer_distribution.py tests/test_release_assets.py \
  tests/test_release_publication.py -q --maxfail=1 --tb=short \
  --basetemp=/tmp/pipeline-curl-agent-final-complete
rtk proxy /tmp/internship-pipeline-audit-venv/bin/ruff check tests/test_curl_installation.py
```

Result on the final reviewed implementation: **132 passed in 15.03 seconds**; Ruff and formatting checks passed for the new acceptance tests. The pipe-only subset passed **21 tests in 5.91 seconds**. These are overlapping sets, not additive counts.

Parent integration then passed the complete native suite: **944 passed in 123.96 seconds**, using `PYTHONPATH=src`, the same audit interpreter and `python -m pytest -q --basetemp=/tmp/pipeline-curl-final-20261008 --tb=short`. There were no skips; one dependency deprecation warning came from FastAPI's test client. Full Ruff and strict mypy across 66 source files passed. Documentation checks and workflow YAML/shell/embedded-Python parsing passed; actionlint was unavailable. These checks do not establish live hosted or provider acceptance.

## Independent security review

The download, extraction, installer-default, asset builder and publication paths were reviewed read-only outside the acceptance tests. The final reviewed code has no unresolved actionable finding within this scope:

- Launcher metadata is validated before rendering; versioned URLs and hashes are fixed. Curl ignores `.curlrc`, permits HTTPS for the request and redirects, bounds time/size, and writes into a private temporary directory. Real Python verifies the bootstrap before execution. The outer shell compound command prevents a truncated prefix from starting the download/install body.
- Bootstrap verification precedes installer execution, and extraction writes only fixed allowlisted regular filenames after validating the entire archive. Stored paths, links, owners and modes cannot select destinations. Release image defaults are applied under the installer lock only to a fresh install; saved installations and explicit recovery retain their image authority.
- Release assets come from a clean accepted source and a fixed archive/file allowlist. Input bytes must match the committed source, and executing generator bytes must match that accepted source. Ignored `.env`, private keys, runtime databases and candidate resumes are not enumerated into the asset set. Candidate evidence is deliberately included as sanitized run/image metadata, not environment dumps.
- Workflow inputs enter environment variables and quoted argv, rather than shell program text. Candidate validation requires a successful manual run of the known container workflow on the same repository/default branch and exact source, plus unique unexpired platform artifacts, matching locks/reports/config IDs and hashed OCI blobs. The default branch comes explicitly from trusted workflow repository context; the real run API fixture correctly omits `repository.default_branch`.
- OCI archives are inspected as opaque input, with allowlisted paths and regular files/directories, without general extraction. Promotion uses `--all --preserve-digests`, verifies registry index bytes, and requires the combined descriptors to retain both platform and attestation identities.
- Existing image tags, Git tags and releases are rejected before publication. A new draft prerelease uses the accepted source as `--target` and `--latest=false`. Failed or partial publication requires inspection before retrying; this review did not execute any remote write.

These conclusions cover the reviewed source and controlled assertions. The actual installed Skopeo/Buildx/registry behavior, Actions credential permissions and public access still require execution on the accepted candidate.

## Reviewed source binding

The implementation starts from `fe1b71c` on `codex/curl-installation`, with shared uncommitted curl changes. It is not yet an accepted release source. SHA-256 identifies the reviewed working files; a parent commit and new candidate CI must supply the final immutable source/image binding.

| File | Reviewed SHA-256 |
| --- | --- |
| `deploy/release_launcher.py` | `fe1bcd502c5ea02cfe3f9b215ac861a8bf67750de84ebbdd22aae6591756f51e` |
| `deploy/bootstrap_installer.py` | `431a9dc06b838fb93d94a698226ba6e6edc86772c4b1586566216b1c9c0fcca2` |
| `deploy/install.py` | `c4823aa0e2b964cfa2eb5ec55456b7e0b9de666a252fa4d60ed5abc646a52dc9` |
| `deploy/build_release_assets.py` | `ec12dd0ea3077cea56d3c229e8281f945db23782ece3742b937f0744cae84664` |
| `deploy/publish_release.py` | `db1ba6a687c9585604437112c79d246118085348ee29cca3ed16c9e8338ab92a` |
| `.github/workflows/publish-release.yml` | `41dd04ea26bd4e278aefee5a7e93d0d61c19cf2c6acd80214dddec687dc77dfd` |

Recheck these identities after any security repair. This table does not certify a dirty tree by borrowing the base commit's CI.

## Hosted acceptance still required

Parent's read-only GitHub inspection in this session found no releases and reported the repository private; this task made no visibility changes. [Container candidate run 37838328196](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37838328196) succeeded at `df4835f7674007de38a45045f593c5a0b314b680`. That predates these curl changes and cannot certify the new installer or publication helper. Parent reports offline main `fe1b71c` also passed; it is likewise baseline evidence only.

The minimal handoff is a final clean curl source SHA, successful manual same-source container candidate with both platforms and Docker/Podman reports, an explicit version and reviewed draft/publication decision, and release/package access that works anonymously. After publication, bind the exact launcher/bootstrap/bundle hashes and multi-platform registry digest from release metadata. Use a new synthetic installation on each declared real host/runtime support cell; record host/runtime versions, anonymous HTTPS/registry access, pinned bytes/image, healthy readiness URL, browser owner setup, installed management without a checkout and rerun preservation. Keep owner setup tokens, credentials and candidate facts out of screenshots, logs and evidence.

Until those gates pass, document the versioned curl command as a future hosted command rather than an available installation URL. A prerelease uses `/releases/download/VERSION/install.sh`; `/releases/latest/download/install.sh` requires an actual accepted stable release. See [publication procedure](curl-publication.md) for the prepared workflow and partial-write handling.
