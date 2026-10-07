# T09 — persisted jobs workspace

Implemented October 6, 2026. The approved list/detail job board now queries the authoritative SQLite inventory. Settings remains a separate route; T07's compact persisted search progress and T12's independent manual résumé component mount in the existing workspace.

## Completion evidence

1. All seven named fields sort ascending and descending in SQL, with unknown dates, blank text/locations and absent current fit last in both directions. Stable job IDs break ties independently of direction. Fourteen parameterized cases inspect every row across six pages, including nulls and ties. Dates use SQLite calendar normalization; malformed deadlines sort as unknown. Only a bounded 25/50/100 row page is materialized as job models.
2. Page, page size, search, view, sort, direction and selected job ID persist in the URL. Search runs in the database and selection can stay visible outside the current page or view. Direct reload restores page 400 and selected detail. Superseded responses cannot replace newer queries or selections; background refresh preserves unfinished notes and page drafts.
3. Recommendations, Needs review, Saved, Applied and Rejected are authoritative persisted views. Recommendations/review use the current revision identity, or a recorded owner override. Stale assessments lose their fit and recommendation membership. Rejected contains owner-dismissed or explicitly rejected jobs, and remains inspectable. Automatic model rejection stays disabled because T02's gate failed; no rejected model outcome is manufactured.
4. Detail preserves the original plain posting text, bounded and escaped, original application link, selected posting evidence, confirmed candidate evidence, gaps/uncertainty, criterion distributions, job/profile/model/rubric revisions and usage/attempt history. Existing hostile-evidence desktop/mobile regression fixtures use the new pagination contract.
5. Notes, saved/dismissed state and timestamped decision-override history persist in independent SQLite tables. Override history records the current assessment identity and a required owner reason, including clearing an override. Overrides never alter stored Jev assessments. Explicit mark-applied/undo continues using the existing stored application timestamp and is independent of saving, dismissal, viewing, posting links and résumé downloads.
6. Chromium verifies actual owner authentication, 10,000 stored jobs, 25-row bounds, saved notes/selection after reload, explicit rejected/applied views and override history, page 400, Enter selection, detail focus, Escape focus restoration and a 390 × 844 layout without horizontal overflow. The screenshot is ignored at `web/test-results-t09/t09-mobile.png`. Search progress changed throughout the timing run.

## Verification

Focused Python command: `rtk proxy env PYTHONPATH=src .venv/bin/python -m pytest tests/test_owner_app.py tests/test_job_workspace.py tests/test_dashboard_api.py -q` — **49 passed**. Ruff passes the changed Python modules/tests, mypy passes both workspace/dashboard source modules, The two existing assessment desktop/mobile Chromium regressions pass in **3.5 seconds**. Svelte check reports **0 errors/0 warnings**, and the static build passes. `rtk git diff --check` passes.

From `web/`, `rtk proxy npm exec playwright -- test --config=playwright.t09.config.ts` runs the isolated real-HTTP fixture on loopback port 4189 — **1 passed in 15.0 seconds**. The temporary database/key and server are removed after testing. The suite has its own ignored artifact directory to avoid interference with parallel task verification. Fixture data is synthetic and no provider calls occur. Ordinary `npm test` excludes this separately configured fixture, as it excludes the other standalone servers.

## Real API and database timing

Reference machine: MacBook Pro18,1 / Apple M1 Pro, macOS 26.6.2 arm64, headless Chromium, 1440 × 1000. No network/CPU throttling; concurrent task activity and background load are uncontrolled. The test stores 10,000 synthetic jobs and 7,500 current synthetic persisted assessments in SQLite, then measures authenticated browser fetches through the actual FastAPI router, revision-aware SQLite queries, model validation and JSON serialization. Each measured iteration runs jobs and current-progress HTTP requests concurrently, waiting for both decoded responses. A separate writer updates stored progress every 100 ms; progress advanced from 35 to 127 during the recorded samples.

Ten samples per sort alternate ascending page 400 and descending page 1. Median uses the sixth sorted sample; nearest-rank p95 is the maximum for ten samples. These are paired API response timings, including the progress read; they are not DOM/frame/INP measurements or isolated SQL timings. They include no simulated response delay and are distinct from T01's worker transport experiment. Raw samples and summaries are committed in `web/reports/t09-real-api.json`.

| Sort field | Median | p95 |
| --- | ---: | ---: |
| postedAt | 169.6 ms | 260.4 ms |
| firstObservedAt | 87.9 ms | 101.2 ms |
| company | 123.3 ms | 131.0 ms |
| title | 123.1 ms | 241.0 ms |
| location | 184.1 ms | 218.1 ms |
| deadline | 156.4 ms | 176.5 ms |
| score | 212.2 ms | 250.8 ms |

## Supported boundary

This completes T09's six criteria. T08 owns schedule/cancel/run budgets and reconnecting progress beyond T07's persisted polling; T12 owns document generation quality/live provider acceptance; T14 owns alerts. Keyboard and Chromium mobile behavior are verified; screen-reader operation, other browsers, low-end hardware, and deployed latency remain unverified. Owner overrides are personal review decisions rather than validation of model accuracy. No real candidate inputs, notifications, paid inference, deployment, commits or pushes were performed by T09.
