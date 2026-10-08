# Support and resource acceptance — October 8, 2026

Status: local subset verified; serving-image, screen-reader, host matrix and operating-trial acceptance remain open. Concurrent release CI and multi-provider development mean this is not a frozen candidate certification.

## Completed native checks

The existing `web/tests/t09-serve.py` fixture no longer matched the current `search_runs` schema. It now supplies the required search identity and explicit zero model-work budgets. Its synthetic progress thread performs local SQLite updates only. The corresponding browser test now exercises 320px as well as 390px and closes a persisted detail before opening a new job in the mobile layout.

One real HTTP/SQLite browser case passed again in 18.3 seconds, using 10,000 synthetic jobs, the built frontend and installed headless Chrome through Playwright 1.63.0. It covered owner claim, pagination to page 400, sort/reload URL state, saved jobs, notes, explicit rejection override, Applied/undo UI availability, job detail keyboard focus, Escape focus return and no horizontal overflow at 320px/390px. It also confirmed progress advanced while querying the stored inventory and saw no browser page errors. External providers/workers were not involved.

Command: from `web/`, `rtk proxy npx playwright test --config /tmp/pipeline-release-t09.config.ts`. The temporary wrapper imports the committed `playwright.t09.config.ts`, sets absolute paths and selects installed Chrome rather than downloading a browser on the low-disk host. The first attempt exposed the stale schema; a later test exposed the outdated assumption that mobile detail was closed after URL-state restoration. Both fixture assumptions were corrected before the passing run.

Host: Darwin 25.6.0, arm64. Exact CPU model and physical RAM were unavailable to the restricted shell, so these results cannot establish minimum hardware requirements. Ten sequential samples per sort each timed the *combined completion* of a jobs page request and a current-run request on local loopback, alternating page 1/400 and sort direction. These are elapsed browser fetch timings, not isolated SQL latency or production p95 guarantees.

| Sort | Recorded median (ms) | Maximum of 10 samples (ms) |
| --- | ---: | ---: |
| Posting date | 166.7 | 186.0 |
| First observed | 100.1 | 138.9 |
| Company | 129.5 | 144.1 |
| Title | 131.4 | 242.0 |
| Location | 163.8 | 226.3 |
| Deadline | 145.9 | 179.6 |
| Score | 217.0 | 269.7 |

Independent review caught the previous test's upper-median calculation. The test now averages the two middle samples; the table uses the final rerun and computes that median from the retained raw samples in [native-workspace-timings.json](native-workspace-timings.json). The largest of ten is the nearest-rank p95, labeled maximum here to make the small sample explicit. Raw synthetic timings/screenshots stay in ignored `web/test-results-t09/`.

## Actual static compression

The application previously mounted `StaticFiles` directly. It now wraps only that mount with the existing Starlette `GZipMiddleware` (500-byte threshold); API responses remain outside the compression scope. A response-level regression verifies gzip content and length, `Vary: Accept-Encoding`, identity negotiation and an authenticated jobs response larger than the threshold remaining uncompressed. A static-only adapter enforces exact encoding tokens and quality values before delegating compression to Starlette, including explicit refusal and 406 when neither supported representation is acceptable. The focused static/owner/resource set passed 49 tests; Ruff and strict mypy passed.

`rtk npm run measure` passed: 18 independently compressed JavaScript assets total 221,434 raw bytes, 80,309 gzip bytes and 70,187 Brotli bytes, below the 200,000-byte gzip budget. Brotli is a bundle measurement only; the application change serves gzip. The rebuilt release image must independently verify actual response headers and network bytes. See [Starlette middleware documentation](https://github.com/kludex/starlette/blob/main/docs/middleware.md).

## Resource sampler ready for an accepted installation

`deploy/measure-resources.py` reads numeric counters from a running installation selected through its private `installation.json`. It reuses the saved runtime endpoint and ownership validation; it never starts the engine/container, triggers work or resets kernel counters. It requires a private cgroup-v2 namespace and rejects changed container/image/start identity or reset CPU counters. Reports use an unused owner-only output file and contain numeric counters/image identity rather than secrets or container logs.

Run each phase against the accepted image and record workload/job/document identities separately:

```sh
python3 deploy/measure-resources.py \
  --install-dir "$HOME/.local/share/internship-pipeline" \
  --phase idle --seconds 30 --interval 1 --report /tmp/pipeline-idle.json
```

For `--phase run` or `--phase pdf`, start the sampler around the separately authorized workload and record its exact start/end. The label alone does not verify that workload happened. Sampling includes the probe process overhead and can miss short peaks; `memory.peak` describes the container lifetime and is not falsely attributed to the selected phase. A missing kernel peak is reported as null. Disk free space describes the backing filesystem, not only application data. Unsupported cgroup namespaces fail explicitly. The [Linux cgroup-v2 reference](https://cdn.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) defines the counters.

Seventeen focused resource measurement tests passed with fake saved runtimes and synthetic kernel reads, covering bounded duration, numeric allowlisting, no start of stopped instances, restored data-root selection, changed/reset containers and rejection of host-wide counters. These tests do not supply real container measurements. Strict mypy and Ruff cover the new helper.

## Remaining measured support gates

| Gate | Required evidence |
| --- | --- |
| Browser declaration | Exact browser/OS versions and supported targets; native Chrome results do not imply other engines. |
| Real screen reader | Named screen reader/browser, operator and observed focus/dialog/error/progress announcements through setup, jobs and Settings. Automated focus assertions cannot replace this. |
| Serving image | Repeat network compression, 10k interaction and responsive checks against the accepted source/image identity. |
| Runtime/resources | CI lifecycle reports plus actual idle/run/PDF samples; build duration, image size, engine/host versions and disk headroom. |
| Registry pull | Cold pull/start timings after candidate publication, with network/cache context; assigned to hosted installer acceptance. |
| Host installers | Every advertised OS/architecture/runtime cell tested by an unfamiliar operator, or an explicit narrowed support declaration. |

## Operating trial disposition still required

`docs/implementation-plan.md` Step 12 still calls for a representative 24-hour run, cadence/latency measurements and user inspection of matches/documents. It has not been run here and has not been silently removed. The owner must either retain that trial for this release or explicitly approve a narrower first-release scope. Until then this row stays open.

For the retained trial, use the current saved searches, independent model/document/email/Sheets workers and supported provider contract. Select the source set/role families, synthetic profile, host, request/usage limits and destination before starting. Record successful checks, missed schedules, first observation, decision time, queue delay, actual receipt and errors; reconcile every selected opportunity with a delivered or inspectable recoverable/final outcome. The historical 30-second alert and two-minute PDF targets are unmeasured and digest timing must follow its configured window. Failure injection should use synthetic transports and owned resources. Retire historical Resume Matcher/Dot/local-model instructions instead of attempting removed paths.
