# Step 1: repository findings and implementation map

Analyzed October 6, 2026: `Luke-Pitstick/internship-pipeline`, `main`, commit `8f97967` (`Enable original LaTeX generation after real Render acceptance`). The repository was fetched into the current workspace. Existing `OPEN_SOURCE_PLAN.md` and `FEATURE_WISHLIST.md` were preserved. This analysis changes planning documents only.

## Decision

Keep the Python pipeline and its SQLite infrastructure. Build the Svelte dashboard in this repository, introduce a FastAPI application around the existing domain services, and replace matching with a single persisted Jev assessment consumed by every downstream feature. Replace subscription-specific résumé generation with the configured general LLM, retaining useful factual checks and the PDF compiler.

The initial proposal to introduce Huey is withdrawn. `queue.py` already implements expiring ownership, heartbeat renewal, bounded retries, dependency deferral, and manual retries, while `storage.py` enqueues tasks transactionally. Replacing this would discard working behavior and add a second source of task state.

## What is already here

| Area | Evidence and decision |
| --- | --- |
| Sources and normalization | Keep `sources/ats.py`, `sources/jobspy.py`, `sources/jobspy_worker.py`, `collection.py`, and `normalization.py`. Direct ATS collection and subprocess-isolated broad search already feed a common job model. |
| Source lifecycle | Keep first-snapshot backlog, separate timestamps, identity/deduplication, incomplete-inventory handling, and closure/reopening safeguards in `storage.py`. Those protect against false new-job alerts and mistaken closures. |
| Scheduling and durability | Keep `scheduler.py`, `queue.py`, `maintenance.py`, and `supervisor.py`. Add product controls and run records around them. |
| Notifications | Keep Apprise in `notifications.py` and durable delivery bookkeeping. It already covers email transports; the missing work is configuration, policies, and UI. |
| Candidate facts | Extend Pydantic `CandidateProfile`, `ExperienceFact`, and `Constraints` in `models.py`. Stable fact IDs and profile hashes are useful foundations for evidence and invalidation. |
| Résumé verification | Retain applicable grounding/provenance checks, protected values, bounded compilation, PDF text/page checks, checkpointing, and stale-result suppression. Separate these from template-specific editing constraints. |
| Application status | Keep explicit, idempotent mark-applied behavior. Downloading a PDF and sending an alert must continue to be distinct from submitting an application. |
| Tests and CI | Retain the regression suite and frozen `uv.lock`; extend CI to the frontend and a complete image smoke test. |

Runtime dependencies include Pydantic, httpx, PyYAML, Apprise, pypdf, `ats-scrapers==0.3.0`, and `python-jobspy==1.2.0`. The lockfile resolves actual versions. There is no frontend package manifest, frontend source tree, FastAPI dependency, Jev client, user-account subsystem, or Google Sheets API client in the tracked application.

## Findings that change the implementation order

### 1. One-container backend deployment already exists

`deploy/web-entrypoint.py` supervises the results API and pipeline; the pipeline supervisor starts collector, matcher, resumes, delivery, and discovery. `Dockerfile` bundles Python, Codex/Node, and TeX. However, `compose.yaml` still starts five worker containers and omits the results API/frontend. The Render path also waits for `/var/data/activated` after manual provisioning of configuration, profile, résumé, and subscription login.

**Change:** make one application entrypoint and one-service Compose definition the normal deployment. Serve setup before configuration exists, then activate configured worker capabilities. Remove the Render-only activation-file path. Add frontend build inputs to `.dockerignore`, whose current whitelist would exclude a new `web/` directory. Preserve graceful process-group shutdown. Separate liveness from readiness: `/healthz` currently returns 200 even without working private configuration.

### 2. The API bypasses saved model results

`DashboardAPI._read_jobs()` in `dashboard_api.py` reads up to 1,000 jobs ordered by first observation, runs `_deterministic_match()` on each, and discards jobs that do not pass its keyword/fact checks. It does not read the worker's stored assessments. A 10-second snapshot cache reduces repeated work but does not establish consistent decisions or pagination.

**Change:** store one authoritative assessment and make the API read it. Add server-side pagination, sorting, and explicit views for pending, accepted, review, and rejected jobs. Do not run inference or a second semantic filter on a GET request. Extract useful PDF/link validation and applied-state logic when replacing the standard-library HTTP server with FastAPI.

### 3. Jev must replace the semantic prefilter, not sit behind it

`matching.py` currently runs regex-based eligibility and role filtering first; rejected postings never reach its optional chat-completions call. The generic LLM can assign strong/possible/weak fit but cannot replace the preliminary eligibility outcome. Four role families are hard-coded. `MatchResult` has no numerical fit, confidence, per-criterion outcomes, or model/rubric identity.

**Change:** replace semantic rejection and optional chat-based matching with Jev. Retain data validation, deduplication, explicit application/closed state, and exact numeric/date operations in ordinary code. Define criterion-level `satisfied/violated/not_stated/ambiguous` decisions, score dimensions, evidence IDs, and an explicit review outcome. Extend `MatchResult` and persist the complete assessment.

### 4. Optional notifications currently block core operation

`cli._require_destination()` is called before continuous worker operation. `Pipeline._resume()` also requires at least one delivered opening event before generating anything. With no destinations, that condition can never pass. `Store.save_match()` automatically queues a résumé for every accepted match; pausing the résumé process through an environment variable does not provide a generation policy.

**Change:** store the opportunity first, then independently schedule optional résumé and delivery work. Add separate search inclusion, alert, and résumé-generation policies. Honor the wishlist's automatic-generation toggle and minimum fit/recommendation/eligibility settings. Recheck policy when a task is claimed so disabling generation also stops queued work. Keep manual generation available when automatic generation is disabled.

### 5. Browser settings require revision-aware workers

Settings/profile/company/search inputs currently come from YAML and environment variables. The continuous workers load settings and the candidate profile at startup; the collector registers its configured targets once. The dashboard reloads some configuration independently. Match caching uses only `(job_id, content_hash, profile_revision)`, so changing a model or rubric would not invalidate a stored result.

**Change:** make validated database-backed settings and immutable profile/configuration revisions authoritative. Workers load a revision at task boundaries; evaluation keys include job, profile, rubric, model identity, and relevant policy revisions. Settings changes enqueue appropriate reassessment and suppress stale in-flight outputs. Remove the parallel YAML runtime configuration path after the new flow is complete. Preserve data explicitly; do not silently reuse incompatible stored assessments or delete a user's database.

### 6. Résumé generation is personal and template-specific

`resumes/codex.py` invokes Codex with `forced_login_method="chatgpt"`, using a saved subscription login. General LLM credentials in Settings currently belong to matching, not résumé generation. `resumes/latex.py` requires a `.tex` master and editable `\resumeItem{...}` spans; `CodexResumeGenerator` and its validators require bounded, same-length edits. PDF-only source is explicitly rejected. There is no PDF/DOCX-to-profile import flow.

**Change:** introduce a general-LLM document generator and an application-owned résumé template fed by confirmed structured facts. Add PDF extraction using the existing pypdf dependency and a maintained DOCX parser only after selecting its required contract. User review turns extracted facts into authoritative input. Reuse source-grounding and PDF checks, but do not impose old character-count/template rules on the new structured document workflow. Remove the old subscription-only generator and its image dependency rather than maintain a fallback. TeX remains a significant image dependency until measured otherwise; a light dashboard does not imply a tiny container.

### 7. The frontend and spreadsheet integration are outside the product

`docs/dashboard.md` describes an external authenticated Sites frontend proxying the Render API with a shared bearer token. Its source is not in this repository. The Render outbox sync script downloads events over SSH for a local Codex relay; it is not a self-contained Google Sheets connector.

**Change:** create `web/` for the Svelte application with account creation, session login, onboarding, jobs, profiles, and settings. Replace shared-token-only access with owner sessions and a protected first-run claim. Build an in-container Sheets connector with credential setup, stable-ID upserts, checkpoints, and user-column ownership. Remove the SSH/local-Codex relay requirement from the product. Keep Apprise for email rather than building another notification stack.

## Concrete module map

Proposed new paths are destinations for implementation, not files created by this analysis.

| Work | Existing paths | Proposed additions / outcome |
| --- | --- | --- |
| App bootstrap and deployment | `Dockerfile`, `compose.yaml`, `deploy/*entrypoint.py`, `supervisor.py`, `.dockerignore` | `app.py`, one setup-aware application entrypoint, one volume and port; retain five logical roles. |
| API and owner identity | `dashboard_api.py`, `models.py`, `storage.py` | `api/`, `identity.py`, settings/profile persistence, bounded uploads, sessions, setup claim. |
| Jev evaluation | `matching.py`, `prompts/match.txt`, `MatchResult`, match storage/cache | `evaluation/jev.py`, `evaluation/rubrics.py`, `evaluation/policy.py`; one persisted result used everywhere. |
| Independent side effects | `cli.py`, `pipeline.py`, `Store.save_match()` | Separate admission, auto-generation, and alert policies; reuse existing queue operations. |
| General LLM and résumé import | `resumes/codex.py`, `resumes/service.py`, `resumes/latex.py`, `resumes/validation.py` | `llm.py`, `profiles/imports.py`, owned template and structured document generation. |
| Dashboard | Current frontend absent | `web/`: Svelte/TypeScript, static build, paginated jobs/detail panel, setup and grouped settings. |
| Optional delivery | `notifications.py`, `dot.py`, `scripts/sync_render_outbox.py` | `integrations/sheets.py`, destination settings, digest scheduling; remove personal relay dependency. |
| Release | README, docs, CI, image build | Current documentation, license, synthetic onboarding fixture, image publishing and install/recovery smoke tests. |

Use the existing module seams; do not introduce a generic plugin system or separate service architecture. Svelte remains the recommended frontend because there is no in-repo React implementation to preserve. Actual table/form/progress performance is still a prototype gate, not a measured result.

## Recommended first implementation slice

1. Define the revised evaluation, profile, and settings contracts, including generation/alert policies and revision keys.
2. Add the setup-aware FastAPI application and owner session flow; persist a confirmed profile and tested model settings.
3. Integrate Jev with the existing matcher worker and write authoritative, versioned assessments. Remove the API's independent keyword screening.
4. Decouple delivery from collection/generation and enforce the automatic résumé policy at enqueue and execution time.
5. Add a thin Svelte setup/jobs/settings UI, then package that working flow with the existing supervisor and one-service Compose.

Acceptance: a fresh deployment can claim an account, configure models/profile/search, collect from an existing supported source, and inspect Jev decisions with no notification destination or subscription login. Follow with the generalized résumé path, richer dashboard, and optional integrations. Every implementation slice must preserve the source and queue invariants covered by the current suite.

## Baseline verification performed

| Check | Current result |
| --- | --- |
| Frozen dependency install | Passed using Python 3.12.7 and `uv sync --python 3.12 --frozen`. |
| Unit/integration suite | **378 passed in 10.14 seconds**, no skips, including an actual synthetic `pdflatex` compile. Model calls use test doubles; this is not live model evaluation. |
| Ruff | Passed for `src` and `tests`. |
| mypy | Passed for 29 runtime source files. |
| Compose | `docker compose config --quiet` passed; this validates the current five-service definition, not the proposed image. |
| Offline demo | One generation, two recorded messages, and zero additional messages on repeat ingestion; no external services called. |

The first sandboxed test run could not bind localhost sockets. Several generated executable fixtures also failed because their shebang uses `sys.executable` under a path containing spaces. Running the same installed environment through a space-free `/tmp` symlink with local-server permissions passed the complete suite. Record this as test portability debt; no production code was changed to make tests pass.

No Docker image was built in this audit, no deployed service was changed, and no private profile, real application, or external notification was used. Source behavior was inspected locally after automatic approval review rejected whole-repository indexing over possible source/configuration transmission.

## Step 1 completion and remaining proof

- Complete: repository acquisition, architecture/dependency inventory, keep/replace/delete map, baseline verification, and concrete implementation priorities.
- Pending: prototype the jobs table, profile/settings form, and live progress view; record actual bundle and interaction measurements.
- Pending: a credentialed Jev evaluation on synthetic/approved labeled data, with false-rejection, review-rate, and ranking results. Existing matching tests are useful regression cases, not evidence that Jev meets the desired quality.
- Pending: a complete new-image build and installation/restart test, plus published resource measurements for both supported CPU architectures.

The repository's older implementation and acceptance documents reference Resume Matcher, a previous 195-test baseline, and past deployment limits. Later code and deployment documentation describe original-LaTeX generation and a consolidated Render service. Keep historical evidence identified as historical, and make the new release's claims match new verification. No root project license exists in this checkout, so an explicit license decision is also required before calling the release open source.
