# Combined repair verification — October 8, 2026

**R1–R5 are complete for the local native/synthetic repair scope. All 16 original findings pass independent review, together with the additional repair findings below.** Base HEAD: `3239183c8b2de4a6f3227eac9e750ddb5ce8d53c`. This report describes the local uncommitted repair candidate. It is not evidence of a published release, a successful GitHub Actions run or actual container acceptance.

[Candidate source manifest](candidate-source.sha256) records SHA-256 values for 201 source, test, frontend and deployment/configuration files, including untracked regression additions. Its SHA-256 is `2b4536932473021b63e31bd54ad77de5599df9d49c2fb3afdfd88070c75b5dcb`. Documentation is outside that manifest so completion reports can be finalized without changing the tested code identity. The parent rechecked every listed file after the final browser build. A future commit/run SHA must be associated with these bytes before using this evidence for CI acceptance.

## Independent defect closure

| Finding | Current independent status | Evidence |
| --- | --- | --- |
| B1: saved-search ownership and budgets | Pass | [Backend review](backend-independent-review.md) |
| B2: atomic SMTP/queue outcome and uncertain recovery | Pass | [Backend review](backend-independent-review.md) |
| B3: stale email/digest membership | Pass | [Backend review](backend-independent-review.md) |
| B4: retry ceilings isolated by task kind | Pass | [Backend review](backend-independent-review.md) |
| B5: complete CSV and explicit Sheets capacity | Pass | [Operations review](data-operations-independent-review.md) |
| B6: multi-source canonical closure | Pass | [Backend review](backend-independent-review.md) |
| W1–W6: editor revisions, saved Sheets form, anonymous admission, dirty drafts, mobile history, malformed hash | Pass | [Independent web review](web-independent-review.md) |
| O1–O4: backup URI/identity, stderr logs, shipped config, stopped recovery | Pass within native/prepared scope | [Operations review](data-operations-independent-review.md) |

Further review found stale draft revisions after automatic-generation preview (W7) and delayed model tests (W8), Reload remaining available during an email save (W9), a failed setup navigation clearing the dirty guard (W10), and incomplete CSV reader cleanup after transport failure/disconnect. All have repairs, retained regression coverage and independent sign-off. The operations reviewer independently verified CSV closure inside the ASGI coroutine before event-loop teardown, preventing teardown from masking a leaked reader.

## Combined native checks

After Python source and tests settled, the parent ran:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q --basetemp=/tmp/pipeline-repaired-combined-20261008-b391 --tb=short
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src tests deploy
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m mypy --strict src/internship_pipeline
```

**692 Python tests passed in 87.03 seconds, with no skips.** The only warning was the existing Starlette/httpx TestClient deprecation. Full Ruff passed, and strict mypy passed across all 55 source modules. These checks use synthetic provider transports, temporary stores, actual local processes and the installed PDF compiler. They do not call a real model provider, send mail, write a remote spreadsheet or run a container engine. Reviewer subset counts overlap this total and must not be added to it.

The final built JavaScript totals 220,380 raw bytes, 80,006 gzip bytes and 69,888 Brotli bytes across 18 independently compressed assets; `npm run measure` passed the existing 200,000-byte gzip budget. This is bundle measurement, not observed network latency or a cross-browser performance guarantee.

## Browser and frontend checks

Svelte checking completed with **zero errors and zero warnings**, and the production build passed. The author ran **35 browser cases** across six isolated fixture suites: 25 web/security regressions, six default application cases, and one each for fresh setup, email, Sheets and generation policy. The independent reviewer also reran all 25 web/security cases successfully and passed an additional profile-draft variant of W10; the dedicated rerun overlaps the total. [Web repair evidence](web-security.md) and [independent web review](web-independent-review.md) distinguish each observer's exact commands and results.

Final local browser execution used installed headless Google Chrome 155.0.8059.39 with Playwright 1.63.0 and temporary wrapper configurations, because the downloaded Playwright Chromium executable was unavailable. Committed configurations remain portable and the prepared GitHub workflow installs Chromium. No browser was downloaded on the low-disk host. This verifies one local browser engine and synthetic external transports, not a cross-browser/screen-reader matrix or live-provider journey.

## Package inspection and repair

The parent built the real source distribution and wheel with `uv build`, then inspected archive filenames. The source distribution unexpectedly included generated `web/node_modules`, `.svelte-kit`, and `test-results*` directories, including synthetic session/setup output. The root ignore rules did not exclude those nested frontend outputs from the build. Explicit source-distribution exclusions now omit the generated frontend directories; a durable CI archive-content check rejects them in either distribution. The same guard failed on the original archive and passed against both rebuilt artifacts in `/tmp/pipeline-repaired-package-clean-20261008`: source archive 5,637,424 bytes, wheel 132,801 bytes. This package check does not replace the broader license/image redistribution review.

## Release boundary

[GitHub Actions preparation](github-actions-candidate.md) records the owner's selected build environment and prepared native amd64/arm64 Docker/Podman recovery matrix. The workflow first gates on code/browser checks and retains diagnostic artifacts on failure. Execution still needs the exact reviewed candidate available remotely and dispatch authorization; running the existing remote revision would not test this local diff.

R6 image/runtime acceptance, R7 bounded live-provider/integration acceptance, R8 license/distribution decisions, and R9 hosted installation remain open. Fresh supported stores are covered; no older-schema compatibility or migration claim is made. Jev model rejections remain reviewable pending the separate quality gate.
