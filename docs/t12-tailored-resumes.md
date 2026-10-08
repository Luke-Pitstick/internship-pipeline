# T12 — Job-specific drafts through the configured general LLM

Implemented October 6, 2026. Select a job in the authenticated workspace and request a job-specific résumé. The existing saved general LLM connection supplies the model and credential; notification destinations are unnecessary. Automatic generation is controlled by the separate, off-by-default [T13 policy](t13-generation-policy.md).

## Supported generation and grounding contract

The general LLM supports the official OpenAI Responses, Claude (Anthropic) Messages and OpenRouter Chat Completions endpoints from T05. Settings → AI Models selects the provider and model. Each API requests structured JSON output, with no redirects, environment proxies or application-level provider fallback. OpenAI requests set `store: false`; OpenRouter routing requires parameter support and disables provider fallbacks. Each provider has its own retention policy. Requests contain only confirmed résumé fact records and the selected posting title, employer and description, explicitly identified as untrusted matching data. Name, contact details and education stay local to the deterministic template; unknown facts, eligibility inputs and preferred skills cannot become generated claims.

The model returns a structured ordered list of confirmed fact IDs. The application validates IDs, uniqueness and nonempty selection, then renders original confirmed wording verbatim. This is intentional job-specific selection and ordering within fixed sections, not unrestricted prose rewriting: preserving each entire supported statement gives a mechanical grounding guarantee for qualifications, numbers and dates. The UI displays selected and omitted original statements and unknown statuses so the owner can inspect exactly what changed. Unsupported or fabricated IDs fail before compilation. The profile evidence records in the manifest retain their original source provenance; contact, education, selected skills and every original factual character must survive readable PDF extraction.

The same application-owned two-page template, character escaping, bounded `pdflatex` process group, no shell escape, restricted TeX file access, readable-text/contact checks, overflow-log checks and page-bounds checks serve master and tailored generation. Uploaded or model-supplied TeX is never executed. Obsolete source-edit spans, exact-character-count rules and personal-template restrictions have been removed from the compiler.

## Durable work, review and private delivery

`TailoredResumes` creates `tailored_resumes` and `tailored_attempts` in the shared jobs SQLite database and uses the existing `tasks` queue with kind `tailored_resume`, lease heartbeats and at most three attempts per task. The API returns queued status immediately; the supervised `tailored-resumes` worker runs independently of collectors and delivery workers. Progress records selecting, validated selection, compilation and awaiting review.

Each provider attempt is reserved before HTTP I/O, with sanitized status, exact model revision and effective model/token metadata (missing usage is unknown). A crash leaves an inspectable pending attempt. Validated selection is checkpointed durably before compilation so compiler/storage recovery does not repeat inference. Retryable HTTP quota/server failures use the queue backoff and bounded attempts; authentication, unsupported model, timeout with unknown usage, malformed output and grounding failures require owner attention. Each deliberate retry reuses the same unique task and checkpoints.

The artifact identity includes stable job content/opening revision, immutable saved profile revision, model configuration revision, template digest and grounding-policy revision. Routine collector observations do not invalidate it. Concurrent identical requests share work; unchanged successful output is reused. Profile/model/posting changes suppress previous drafts immediately, and a changed revision or lost lease prevents completion publication. Missing, corrupt and symlink artifacts fail safe; a deliberate generation request can rebuild a corrupt cached PDF using its validated selection.

PDF directories are private (0700), files are private (0600), generated names are fixed and bounded, reads use no-follow descriptors and stored SHA-256 verification. The same owner-session/CSRF/origin checks protect generation, review and downloads. APIs expose no private paths or credentials:

- GET/POST `/api/jobs/{job_id}/resume` reads or requests the current draft, using expected profile and model revisions.
- POST `/api/tailored-resume/{key}/review` records explicit owner review only for a current completed draft.
- GET `/api/tailored-resume/{key}/pdf` previews inline; `?download=true` downloads with private no-store headers.

A completed result remains a draft until the owner explicitly reviews its selected facts, omissions and warnings. Review/download never submits an application, marks it applied, establishes eligibility or delivers a notification. The owner can download an unreviewed draft, which remains visibly labeled as awaiting review.

## Verification evidence

- 21 focused Python tests pass using synthetic profile/posting inputs and mocked official-provider HTTP transport, including actual `pdflatex` output, cache and corrupt recovery, retained selection after compile failure, stale model suppression, lease loss, unsupported/duplicate/empty fact IDs, missing model readiness, 401/429/503/400 sanitization, the three-attempt cap, unknown usage, refusals/incomplete/malformed responses, timeout without replay, concurrent request deduplication, observation-only cache preservation, owner/CSRF/origin restrictions, explicit review, private PDF download and post-logout denial. The combined T11/T12 suite passed 39 tests (18 master and 21 tailored).
- One dedicated integrated Chromium test passes against a real temporary FastAPI instance and the real tailored queue worker. The HTTP provider is mocked with application-owned synthetic data. The test claims an owner, requests from job detail, inspects selected and omitted original facts, loads the native PDF viewer, downloads, records review and checks 390px layout without horizontal overflow. The downloaded actual PDF was rendered using Poppler and visually inspected: readable contact/education, separated heading rules, preserved protected numbers and no clipping or overlap.
- Focused Ruff/mypy pass; Svelte check reports zero errors/warnings and the static production build passes. Parent coordination owns the final combined suite and shared worker mounting.

Reproduce from the repository with `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tailored_resume.py -q`. Build the frontend, then from `web/` run `npx playwright test --config playwright.tailored.config.ts`. The dedicated fixture uses port 4177 and ignored `test-results-tailored/` output, and does not read any private candidate files or saved provider credentials.

## External verification blockers

No supported general-LLM credential was supplied, so credentialed live generation acceptance for OpenAI, Claude and OpenRouter remains unverified. Mocked transport and successful PDF generation do not count as live provider acceptance. When a supported credential is supplied and a bounded synthetic live request is authorized, verify the selected model's actual structured response, metadata and rendering through this same path. No live paid model request was made for this provider extension, and a Jev credential is never reused as a general-LLM credential.

The Docker host remains unresponsive, so actual runtime image acceptance remains unverified. The Dockerfile retains Node only in its frontend build stage and removes the Codex subscription generator/runtime dependency; native compilation/browser tests do not stand in for an image run. T17 coordinated backup/recovery and T21 release acceptance remain later work.

## Integrated replacement repair

The downstream integration repair removed Pipeline's dangling ResumeService import,
legacy resume task handling, opening-before-generation dependency, terminal résumé failure
notices, artifacts-table hooks, legacy dashboard PDF APIs/metadata, ResumeArtifact,
subscription model/reasoning options and the old synthetic generator. Collection,
authoritative assessment and the configured email Apprise transport remain independently usable.
The obsolete opening/Dot/recording coordinator is removed by the cross-task cleanup.
Master/tailored generation use their own durable task identities and safe authenticated APIs.
The native affected regression suite passed, including real pdflatex T11/T12 generation;
T13 adds atomic automatic policy gates without changing manual request availability.


## October 8 provider extension verification

OpenAI, Claude (Anthropic) and OpenRouter now share the same selection and grounding workflow. The saved endpoint chooses each provider's native request format, authentication and response parsing. OpenRouter supports namespaced model IDs; usage is normalized from prompt/completion counters, and Anthropic cache counters are included in input usage. A provider change requires a supplied replacement key, creates a new immutable model revision and requires a new successful capability test before generation.

- The focused provider/connection/tailored suite passes **86 tests**: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_general_providers.py tests/test_model_connections.py tests/test_tailored_resume.py -q`. It checks native authentication/payloads, strict output contracts, grounding, refusals/truncation/missing usage, bounded errors, revision invalidation and credential isolation. Claude and OpenRouter also pass durable queue execution, real local PDF generation, review, cache reuse and persisted model/usage checks.
- The full Python run passes **831 tests with one skip** and has one sandbox-only failure at the supervisor test's loopback port bind. That exact test passes separately with local-network permission; no product assertion failed in either run.
- The integrated `web/tests/models.spec.ts` browser test passes against the built frontend and temporary real API/SQLite instance. It checks all three provider choices, endpoint/model changes, required replacement keys, discard, save/reload persistence, capability feedback, removal and 390px overflow. Browser capability results are intercepted; Python tests exercise the actual provider client with synthetic HTTP transport. Playwright's missing headless browser was downloaded to `/private/tmp/pipeline-provider-playwright`; reproduce with `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/pipeline-provider-playwright npx playwright test tests/models.spec.ts` from `web/` after building.
- Focused Ruff and mypy pass. Svelte check has zero errors/warnings; the production build and `git diff --check` pass.

These checks use synthetic candidate data. No saved personal credentials were read, no paid live-provider request was made, and this extension was not deployed. Credentialed live acceptance remains open for each provider.
