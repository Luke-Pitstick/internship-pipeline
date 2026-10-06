# Internship Pipeline: open-source product plan

Research date: October 6, 2026. Status: repository audit complete at `8f97967`; product implementation and framework/Jev spikes have not started. See [the step 1 findings](docs/open-source-step-1.md) for verified code paths, baseline checks, and the implementation order.

The proposed execution backlog is in [the task breakdown](docs/task-breakdown.md), including sortable job results and the one-command installer/management wishlist.

## Scope and assumptions

Build a self-hosted application that a person can deploy as one container, claim through their browser, configure with their own model credentials and candidate profile, and use to discover, evaluate, track, and prepare applications. Email and spreadsheet connections are optional.

The repository is [Luke-Pitstick/internship-pipeline](https://github.com/Luke-Pitstick/internship-pipeline), checked out on `main` at `8f97967`. It already contains the Python pipeline, SQLite store and durable queue, five worker roles, a process supervisor, a small protected results API, and original-LaTeX résumé generation. The Sites dashboard frontend is outside this repository. Keep the working backend modules and replace the deployment-specific setup, model coupling, and dashboard transport as described in the step 1 findings.

Initial product boundary: one owner per deployment, with multiple saved searches and résumé versions. Team accounts, shared hosting, billing, and automatic application submission are outside this release.

## Recommended architecture

Use Svelte with TypeScript and SvelteKit routing for the dashboard, built as static assets and served by a FastAPI application. Replace the current `http.server` transport while retaining useful application and download-validation logic. Keep the existing SQLite store, durable task queue, scheduler, five worker roles, and supervisor. Do not add Huey, Celery, Redis, or another queue: repository inspection established that task leases, retries, atomic enqueueing, and recovery already exist.

One published image contains the frontend assets, API, worker/scheduler, search adapters, and résumé rendering dependencies. Extend the existing process supervisor; the Render image already starts the results API and all five worker roles in one container. Replace its manual provisioning and activation-file gate with browser setup. Replace subscription-specific Codex generation with the configured general-LLM client, allowing Node to remain a frontend build dependency only. API and worker health both contribute to readiness; the current unconditional `/healthz` is only liveness. [Docker documentation](https://docs.docker.com/engine/containers/multi-service_container/)

```text
Browser
  └─ one public port: dashboard + authenticated API + progress events
       ├─ SQLite application database
       ├─ background worker and scheduler
       │    ├─ search → normalize/deduplicate → Jev → saved matches
       │    ├─ résumé generation and PDF rendering
       │    └─ email and spreadsheet delivery
       └─ persistent /data volume: databases, uploads, generated documents

External connections: Jev API, general LLM, job/search providers,
                      optional email service and Google Sheets
```

Use separate logical modules for identity/settings, candidate profiles, sources/search, evaluation, documents, and integrations. Share typed domain models between the API and worker. Keep business rules out of routes and frontend components. Avoid a plugin framework until concrete connectors require one.

SQLite is a deliberate single-instance design: use local persistent storage, short transactions, and bounded worker concurrency. WAL permits concurrent readers but still has one writer; do not place the database on a shared network filesystem or run multiple replicas against it. [SQLite WAL](https://sqlite.org/wal.html)

Keep `queue.py`, `scheduler.py`, and the transactional task operations in `storage.py`. Add inspectable search-run records and configuration revisions around them. Separate the existing notification prerequisites from collection and résumé work, and add an explicit résumé-generation policy. Test container-level worker recovery in addition to the existing offline lease/supervisor tests.

## Dashboard framework decision

| Candidate | Assessment for this application |
| --- | --- |
| Svelte + SvelteKit | Recommended for a substantial dashboard redesign: compiled components, explicit routes, and a component ecosystem suitable for forms and job lists. Static deployment fits a separate pipeline backend. |
| Solid + Vite + Solid Router | Strong alternative if retaining JSX is a priority. Its fine-grained updates suit changing pipeline state; assess required component integrations before choosing it. |
| Preact + Vite | Best candidate if the repository contains a large, useful React UI worth preserving. Its React compatibility is substantial but incomplete; concurrent-rendering behavior differs. |
| Existing React | Keep it if inspection shows that replacing it costs more than the measured performance benefit. A framework switch alone will not fix oversized tables or expensive API calls. |

Svelte compiles components into JavaScript that updates the DOM. Solid uses reactive primitives to target updates. Preact documents compatibility differences, so it is not a zero-risk package swap. [Svelte](https://github.com/sveltejs/svelte), [Solid reactivity](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity), [Preact differences](https://preactjs.com/guide/v10/differences-to-react)

For the proposed Svelte implementation, use accessible components from shadcn-svelte where they reduce work, rather than importing a complete admin template. Prototype the actual jobs table, profile form, and progress feed before committing the UI architecture. [shadcn-svelte](https://www.shadcn-svelte.com/docs)

Static SPA deployment removes the frontend server but adds a cold-start rendering cost. SvelteKit explicitly documents this tradeoff. Prerender suitable public shells, split routes, paginate jobs on the server, and lazy-load résumé previews. All private data and mutations remain authenticated at the API. [SvelteKit SPA documentation](https://svelte.dev/docs/kit/single-page-apps)

Provisional performance gates, measured on a documented reference device: at most 200 KB compressed initial JavaScript for login/onboarding, responsive filtering with 10,000 stored jobs using bounded pages, and no interface blocking during a pipeline run. These are product targets, not benchmark results or framework guarantees.

## First-run experience

1. **Deploy and open.** Publish prebuilt images for supported amd64 and arm64 hosts, a one-service Compose file, and a Docker command. Require one port and one persistent volume. The deployment platform supplies the IP or URL; remote deployments need HTTPS from the host's ingress or reverse proxy. Document always-on hosting with persistent storage as the supported environment.
2. **Claim the instance.** On first boot generate a one-time setup token accessible to the operator through container logs. Require it when creating the owner account so an exposed fresh instance cannot be claimed by a stranger. Disable setup after successful claim. Use password hashing, server-side sessions, CSRF protection, login throttling, and an operator recovery command.
3. **Connect models.** Separate Jev from the general LLM. Offer provider, endpoint where supported, model, and credential fields, each with a test request and clear error feedback. Test required capabilities rather than accepting a key's format. Mask credentials and keep them server-side; encrypt persisted secrets with a key supplied or generated at deployment and include key recovery in backup instructions.
4. **Build the candidate profile.** Accept PDF/DOCX résumés and a documented structured profile format. Extract a draft, show its source text, and require review of critical facts. Capture skills, projects, experience, education, graduation date, availability, work eligibility, locations, remote preferences, compensation preferences, and target roles. Distinguish mandatory constraints from preferences. Store profile versions and claim provenance.
5. **Configure discovery.** Choose supported sources, titles/keywords, regions, freshness, schedule, and run budget. Show any source-specific credential requirement. Offer a small test search and a preview of what will be sent for evaluation.
6. **Connect optional destinations.** Configure email and a spreadsheet independently, with test delivery and explicit column mapping. Users can skip both and use the dashboard fully.
7. **Run the first search.** Show progress by stage and finish on a usable list of recommended jobs, with review and rejection decisions accessible alongside it.

Jev is currently documented as a hosted API. This is one-container application deployment with user-supplied model access, not a promise that Jev weights run locally inside the image. General LLM endpoint support must be tested per provider. Keep cloud model data disclosures visible during configuration, and omit contact details from evaluation payloads when they do not affect matching. [TypeSafe models](https://docs.typesafe.ai/models)

## Dashboard product design

The default page should answer “What should I apply to next?” Use a compact navigation rail, a strong job list, and a detail panel that preserves the selected row and filters. Avoid filling the landing page with charts that displace actionable jobs.

| Surface | Main job |
| --- | --- |
| Jobs | Ranked list with company, role, location, deadline, fit, eligibility, and application status; saved views for Recommended, Needs review, Saved, Applied, and Rejected. |
| Job detail | Original posting, source/date, criterion decisions, supporting excerpts, strengths/gaps, résumé action, notes, and apply link. Keep fit and eligibility visually distinct. |
| Searches and runs | Saved searches, schedules, pause/run controls, stage progress, source failures, counts, model usage, and retry actions. |
| Profile and résumés | Editable candidate facts, provenance, missing details, master résumé, generated versions, and document previews. |
| Settings | Model connections, optional integrations, owner credentials, backup/export, and instance health. |

Support keyboard navigation, small screens, visible focus, accessible tables, useful empty states, and direct links to a specific job. Separate discovery state, evaluation state, and application state; a recommended job is not an application.

## Jev evaluation contract

Pipeline: discover → fetch description → normalize and deduplicate → evaluate eligibility and fit → persist → notify/sync. Retain source identifiers, canonical URLs, original posting text, retrieval time, and content hashes. Keep separate requisitions at the same company separate. A failed fetch or expired provider credential must not appear as “zero matching jobs.”

Send Jev a bounded job description, required/preferred skills, relevant candidate facts, user constraints, and validated normalized facts. Use atomic questions instead of a single opaque “should I apply?” prompt. Jev supports Choice, Score, and Noul; questions in a request are independently evaluated against shared state, so dependent decisions belong in subsequent code or calls. [TypeSafe introduction](https://docs.typesafe.ai/introduction)

### Hard filtering

For each mandatory criterion, ask a Choice question with explicit outcomes: `satisfied`, `violated`, `not_stated`, and `ambiguous`. Include work-eligibility compatibility, internship/student status, role category, location/remote restrictions, and other user-declared deal breakers.

Code applies policy: a supported, sufficiently confident violation produces rejection; missing evidence or uncertain answers produce review. A high fit score cannot override a mandatory violation. Confirmed passes proceed normally. Keep rejected jobs inspectable and reversible, and record manual overrides separately from model output.

Jev interprets textual requirements and whether they are mandatory. Exact date windows, salary arithmetic, and numeric comparisons run in code over validated extracted fields. TypeSafe specifically documents weaknesses with arithmetic, dates, irrelevant long context, and adversarial text. Treat job descriptions as untrusted input and test misleading instructions and negations. [Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

### Fit scoring

Ask separate Score questions for skill coverage, demonstrated project/experience relevance, responsibility alignment, and stated career preferences. Define concrete descriptive levels for each dimension. Compute a weighted normalized score in code:

`fit = 100 × sum(weight[i] × score[i] / (level_count[i] - 1)) / sum(weight[i])`

Keep eligibility, fit, and model confidence separate. A fit of 85 means a high position on this matching rubric, not an 85% chance of an interview. Missing essential information should mark the evaluation incomplete rather than silently inflating a score. TypeSafe's Score is a probability-weighted position on descriptive levels, and confidence describes its distribution rather than guaranteeing correctness. [Score semantics](https://docs.typesafe.ai/primitives/score), [confidence](https://docs.typesafe.ai/confidence)

Persist the resolved model version, rubric version, profile version, job hash, per-criterion outputs/distributions, and applicable thresholds. Invalidate cached evaluations when those inputs change. Pin the evaluated model version for releases. Calibrate weights and rejection thresholds on held-out examples before enabling automatic rejection; do not present arbitrary defaults as validated.

### Explanations and résumé generation

Jev does not generate prose. Build primary explanations from criterion labels and validated source excerpts. It can select evidence identifiers from supplied candidates; code resolves them to original text. An optional general-LLM summary must remain grounded in those results.

Use the general LLM to draft and tailor résumés from confirmed candidate claims. Retain the tested `pdflatex` compilation and PDF checks, but make an application-owned template the standard path for PDF/DOCX imports. The existing editor requires `\resumeItem` bullets and same-length replacements, so it is not a generic upload workflow. Extract the useful provenance and factual validators from that template-specific policy; replace the Codex-only generator without retaining a fallback. Validate every added claim against the profile, show a diff, and generate the PDF asynchronously with preview/download. Save the exact profile and job versions used. Limit document-processing resources and compile application-controlled templates rather than arbitrary uploaded code.

## Search and integrations

Reuse working search connectors after repository inspection. Each connector owns discovery/fetching and converts results into one job schema; filtering belongs in the evaluation module. Prefer supported feeds and APIs, with per-source rate limits and explicit errors. General web discovery, where needed, requires a real search connector rather than asking an LLM to invent current listings. Ship at least one useful credential-free source if the existing sources support it.

Email supports score thresholds, immediate alerts or digests, schedules, and test delivery. Use durable delivery records so a temporary email failure does not rerun job search. Handle indeterminate SMTP delivery explicitly; do not promise exactly-once delivery when the provider cannot guarantee it.

Start spreadsheet support with Google Sheets and CSV export. The application database owns job facts and scores; Sheets receives stable-ID upserts. Optionally import only mapped user-owned fields such as status and notes, with conflict detection. Never overwrite arbitrary columns, formulas, or manual notes. Persist sync checkpoints and retry independently. Self-hosted Google authorization requires a deliberate credentials flow: either bring-your-own OAuth app, or a service account with the target sheet shared to it. Do not imply a universal one-click Google connection without that infrastructure. [Google Sheets setup](https://developers.google.com/workspace/sheets/api/quickstart/python)

## Delivery sequence and acceptance gates

1. **Map the existing code and prove the choices.** Repository inventory, keep/replace decisions, and baseline verification are complete in [step 1 findings](docs/open-source-step-1.md): 378 tests, Ruff, mypy, Compose validation, and the offline demo pass. Remaining gates are the dashboard interaction prototype and a credentialed Jev evaluation on held-out eligible, ineligible, and ambiguous jobs. The current suite is evidence for existing behavior, not proof of Jev quality.
2. **Ship a complete single-container vertical slice.** Implement owner setup, one model connection per role, editable profile, one real source, durable run state, Jev eligibility/fit, and a minimal usable jobs screen. Gate: a new user can deploy, configure, search, and inspect decisions without developer tooling or editing configuration files.
3. **Complete the dashboard and documents.** Add search management, saved views, decision inspection, application tracking, profile versions, and résumé tailoring/preview/download. Gate: a user can move from a discovered job to a reviewed tailored résumé entirely in the UI.
4. **Add optional delivery.** Implement alerts/digests, Google Sheets mapping and sync, CSV export, and integration diagnostics. Gate: retries and repeated runs do not create duplicate jobs or spreadsheet rows, and manual fields survive syncing.
5. **Package the open-source release.** Remove personal data and obsolete entry points; choose a project license, check dependencies and redistributed assets, add contribution/security guidance, synthetic examples, architecture notes, deployment/backup/restore instructions, and automated image publishing. Gate: an unfamiliar user follows the README to a working instance, and fresh-install, restart, backup/restore, and supported-architecture smoke tests pass.

Each phase leaves a working application. Do not build all infrastructure first and defer the user journey to the end.

## Release validation

- End-to-end: deploy → claim → connect models → import/review profile → search → evaluate → inspect → generate résumé → optional delivery.
- Failure recovery: container/worker termination at each stage; duplicate schedule triggers; provider timeout/429; lost model credentials; disk pressure; partial sync; restart without duplicate processing.
- Evaluation: held-out human labels, false rejection rate on eligible jobs, ineligible rejection precision, review rate, and ranking usefulness. Include missing sponsorship, conflicting graduation dates, required versus preferred skills, compound negations, and hostile posting text. Set release thresholds from results and keep a regression corpus.
- Privacy and access: unauthenticated API/document access, setup races, CSRF, secret exposure, log redaction, file validation, and backup/key recovery. Evaluate only relevant candidate facts.
- Performance: record image size, pull/start time, idle memory, run memory, dashboard payload, and interactive latency on named hardware. Include document rendering and real connector dependencies before publishing minimum host requirements.

The concrete change list is recorded in [step 1 findings](docs/open-source-step-1.md). The main implementation risks are consistent settings/evaluation revisions across worker processes, calibrated Jev rejection, and generalizing résumé input without losing factual safeguards. Framework measurements, live Jev evaluation, and a new image build remain explicit validation gates.
