# Integrated acceptance — October 6, 2026

## October 7 verification before commit and push

The current combined implementation passed 525 Python tests in 48.35 seconds, with
one existing Starlette TestClient deprecation warning. The run used the same space-free
virtualenv symlink and a fresh `/tmp/pipeline-status-20261007-01` base directory.
Ruff passed for `src`, `tests`, and `deploy`; strict mypy passed all 55 source modules.
Svelte check reported zero errors/warnings and the production static build passed.
The default Chromium/API suite passed six tests in 11.7 seconds; the dedicated fresh
guided-setup suite passed one test in 10.1 seconds. `git diff --check` passed.

These reruns used synthetic test inputs and existing mocked external transports. They
do not establish live general-model, SMTP, Google Sheets, Docker image or portable
installation acceptance. T18 records the actual Colima build's disk-space failure;
its runtime/image/recovery gates remain open.

This acceptance checks the current combined T08–T18 source rather than treating earlier
task handoffs as verification of later changes. Inputs, model credentials and provider
transports are synthetic. Local API, SQLite, native workers and PDF compilation are real;
these checks do not establish live model, SMTP or Google Sheets acceptance.

## Repairs at the integration boundary

The default browser fixture now returns completed onboarding and the current
`{"runs": []}` search-run response for its persisted assessment scenarios. All existing
desktop/mobile assessment assertions pass without weakening them. `setup.spec.ts` remains
excluded by `web/playwright.config.ts`; `web/playwright.setup.config.ts` owns its fresh
installation, port 4184 and isolated output. The checked-in frontend CI runs both the
default suite and this dedicated setup suite after building the static app.

The first combined Python run caught the container recovery fixture's synthetic fetch
function leaking into later onboarding and ATS tests. T18 replaced that global mutation
with a scoped patch and added an assertion that the original fetch function is restored.
Individual fixture tests had passed before this combined run exposed the ordering issue.

True `mypy --strict` additionally exposed untyped SQLite/JSON returns and vendor methods.
Narrow row/data declarations, the concrete ASGI middleware callback type and explicit
Google credential callable/token casts now describe those boundaries. No runtime fallback,
typing suppression, validation removal or provider behavior change was added.

## Direct verification

| Check | Current result |
| --- | --- |
| Default Chromium browser/API suite | **6 passed, 12.7 seconds** after the final source type changes; assessments desktop/mobile, owner claim/login/logout, Settings, model connections, profile/filter revisions and reviewed résumé import. |
| Fresh setup Chromium/API/SQLite/worker journey | **1 passed, 9.2 seconds**, with 7.5 seconds in the test; model correction, synthetic résumé review/reload, independent integration skips, saved-source correction, first useful job and completed reload. |
| Full combined Python suite | **525 passed, one existing Starlette TestClient deprecation warning, 44.73 seconds**, after the recovery mock repair and final source type changes. The run uses a unique temporary directory and approved localhost access. |
| Full source/tests Ruff | **Pass**. |
| True strict mypy | **Pass, 55 source modules**. |
| Svelte check | **Zero errors and warnings**. |
| Production static build | **Pass**. |
| `git diff --check` | **Pass**. |

The first Python attempt reported 515 passes and 10 failures caused by the recovered-fetch
mock leak. After that repair, a concurrent run encountered SQLite disk-I/O and unavailable
temporary database files. The passing rerun used a unique `--basetemp` directory to exclude
interference from shared temporary retention. No product change was needed to resolve
those errors, and their precise environmental cause was not independently established.
Neither failed attempt counts as a pass.

## Reproduction

From the repository root, the existing space-free virtualenv symlink avoids generated
executable shebangs containing the workspace's spaces:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q --basetemp=/tmp/pipeline-integrated-acceptance-20261006-2320 --tb=short
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src tests
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m mypy --strict src/internship_pipeline
rtk git diff --check
```

Choose a new, unused temporary directory for another simultaneous run. Elsewhere use the
project's synced virtualenv; the `/tmp` symlink is only a local verification convenience.

From `web/`:

```sh
rtk npm run check
rtk npm run build
rtk proxy npx playwright test --config playwright.config.ts
rtk proxy npx playwright test --config playwright.setup.config.ts
```

Local native servers require approved loopback access. The earlier T16 automatic-review
deadlines were resolved by the successful approved browser runs recorded here; they were
not bypassed. T16's live-credential journey and T18's actual image/platform/recovery evidence
remain separately assessed in their task documents. No actual résumé, private candidate
input, `.env`, live credential, paid request, external email, remote sheet mutation, commit,
push or deployment was used in this acceptance.
