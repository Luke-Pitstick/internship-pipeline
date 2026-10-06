# T01 — Svelte dashboard validation

Completed October 6, 2026. **Keep Svelte + TypeScript + SvelteKit static deployment.** The synthetic jobs/settings/progress workflow works with bounded pages over 10,000 records, and the full dashboard's compressed JavaScript stays comfortably below the provisional 200 KB target. These results validate this UI slice; they do not establish production API latency, authentication behavior, model quality, or minimum host requirements.

## Delivered behavior

- `/` is a focused job-board view with prominent search, status views, sorting, job cards, selected detail, and compact search progress. Settings is entirely on `/settings/`, following the user's correction to the first generated concept. Both routes are prerendered and directly refreshable as static files.
- All jobs, To review, Saved, and **Applied** are visible status controls. Only the explicit **Mark as applied** action records applied status/date; **Undo applied** reverses it. Viewing a job never marks it applied. Saved settings and applied state survive client-side navigation between routes, then reset on reload.
- The synthetic inventory holds 10,000 records in a Web Worker. Only a bounded 25/50/100-row page is returned to the main thread, with a fixed 35 ms response delay. Search, seven sort fields, direction reversal, and jump-to-page navigation are exercised, including page 400. Missing sort values remain visible after known values in both directions; stable IDs break ties. Stale response IDs are ignored across queries and route navigation.
- Details remain selected when changing page or sort. Posting, first-observed, deadline, and applied dates have separate fields and labels. Match score and eligibility are distinct; unknown dates/locations/scores have explicit labels. No notification timestamp is fabricated because no notification is delivered.
- Settings uses category navigation and focused groups for Profile, Job Filters, Resume Generation, AI Models, and Notifications & Integrations. Save and Discard are explicit, draft changes survive category switching, and invalid submission opens the relevant category and focuses the first invalid field. Validation covers required facts, email syntax, date presence, integer score/day ranges, HTTPS/local endpoints, conditional alert destinations, and `.tex` filenames. The preview never reads or uploads selected files.
- Native buttons, links, labeled inputs, visible focus, a skip link, announced loading/save states, and Enter/Space selection support keyboard operation. At 390 × 844, selection opens the detail view; Back or Escape restores focus to its job card. Settings categories wrap above the form. Neither page overflows horizontally at that viewport. Progress runs, pauses, resumes, completes, and leaves job navigation responsive.

## Reproduction and files

From `web/`, run `rtk npm ci`, `rtk npm run check`, `rtk npm run build`, `rtk proxy npm exec playwright -- install chromium`, `rtk proxy npm test`, and `rtk npm run measure`. Use `rtk npm run dev` for iteration or `rtk npm run preview` after a completed build. The browser suite starts a localhost-only Python static server on port 4174 and stops it afterward; it validates the generated files without a frontend application server. A preview server started before a rebuild can retain stale asset references, so restart it after rebuilding.

All new frontend files are under `web/`. Shared contracts/validation are in `src/lib/jobs.ts` and `src/lib/settings.ts`; progress is in `src/lib/components/SearchProgress.svelte`; preview-only transport/data/session state is in `src/lib/prototype/`. The single static build is in ignored `web/build/`. This task changed no Python modules, root dependencies, deployment files, or shared plans, and created no second production runtime.

Imagegen generated an initial concept and a revised job-board reference using the built-in tool. The final prompt, asset provenance, and user corrections are recorded in `web/design/README.md`. Generated references and actual desktop/mobile screenshots are in `web/design/`; they are not application assets and do not affect runtime payload.

## Verification evidence

- Svelte/TypeScript check: **0 errors, 0 warnings**.
- Static production build: passed; emits `build/index.html`, `build/settings/index.html`, content-hashed JS/CSS, worker, and precompressed assets.
- Browser/domain suite: **7 passed in 17.3 seconds**, including all-sort/null ordering across the full inventory, pagination/search/selection, explicit Applied state/date and navigation continuity, separate static Settings navigation/refresh/save/validation, mobile keyboard/focus, and progress pause/resume/completion.
- A focused measurement rerun while progress was active: **1 passed in 5.5 seconds**. No browser page errors or observed main-thread long tasks occurred during those measured interactions.
- `rtk git diff --check` passed. Dependency install reported zero known vulnerabilities at installation time; this is not a security review.

## Payload and interaction measurements

Reference environment: **MacBook Pro18,1, Apple M1 Pro, 10 cores, 16 GB RAM; macOS 26.6.2 arm64; Node 24.21.0; headless Chromium 153.0.8010.12; 1440 × 1000 viewport**. Mobile functional checks used 390 × 844 on the same machine. Localhost traffic had no network or CPU throttling; system background load was uncontrolled.

`web/scripts/measure-bundle.mjs` sums each static JavaScript file compressed independently using Node gzip level 9 and Brotli defaults. It includes both routes, shared framework code, and the worker, but excludes maps, HTML, CSS, and design images. This **conservative all-route upper bound is 47,114 gzip bytes (47.1 KB decimal), or 41,800 Brotli bytes**, versus 200,000 bytes. Raw JS totals 119,786 bytes. `web/reports/t01-bundle.json` records every asset.

The browser harness separately records JS requested during a fresh root-route load and subsequent jobs interactions, before visiting Settings. Independently recompressing those requested files produces **42,871 gzip bytes (42.9 KB), or 38,405 Brotli bytes**. This includes the worker and conservatively includes error/runtime chunks fetched by the framework. The local static server does not compress responses, so these are reproducible compressed-content sizes, not observed HTTP transfer sizes. `web/reports/t01-browser.json` records paths and raw samples.

For each interaction, the browser captures its native event, observes the matching DOM state after loading completes, then waits two animation frames. Ten warm samples were measured per interaction **while synthetic progress updates were active**; nearest-rank p95 is effectively the maximum with this small sample. These are DOM-plus-frame timings, not standardized INP or a physical-display paint measurement.

| Interaction | Median | p95 |
| --- | ---: | ---: |
| Next page | 63.9 ms | 64.4 ms |
| Reverse sort | 62.8 ms | 65.0 ms |
| Select job/detail | 30.0 ms | 30.4 ms |
| Submit search filter | 61.6 ms | 64.3 ms |

Worker-based pagination/sort/search include the fixed 35 ms simulated response delay. Selection updates existing page data locally. There were no observed >50 ms main-thread long tasks during this measurement window; initialization before the observer was attached is outside that observation.

## Decision and integration boundary

Svelte/static deployment meets T01's needs without adjusting the 200 KB budget. Preserve the approved job-board layout, separate Settings route, Applied view, nulls-last deterministic ordering, focus restoration, explicit Save validation, and bounded page contract. Node is only a build/test dependency; the production API can serve `build/` alongside authenticated endpoints.

T03 should reuse this `web/` app, not create another frontend. It uses SvelteKit 3's Vite-based config, `$app/tsconfig`, and package `#lib` imports rather than obsolete SvelteKit 2 config. Replace the preview-only worker/session modules with authenticated API reads and revisions as the backend becomes available; do not retain them as a production fallback. Server pagination, sorting, eligibility, and stored applied timestamps must be authoritative. Keep private data out of prerendered HTML and client bundles. Current session state contains only synthetic data and must not become shared server-side candidate state.

The login/onboarding shell is not implemented, so its eventual budget still needs verification. Actual HTTP/database timings, reconnecting progress events, authentication/CSRF, persisted settings, model connections, real file validation, résumé rendering, screen-reader use, other browser engines, 320-pixel devices, low-end hardware, and production serving/compression remain unverified. This is a functional framework/design gate, not release acceptance. No dev or test server remains running at handoff.
