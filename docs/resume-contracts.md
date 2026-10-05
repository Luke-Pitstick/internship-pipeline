# Resume Matcher contract and validation evidence

Source inspected October 5, 2026: [srbhr/Resume-Matcher commit 63fc344a9a59a79db6fa9d96aff188dc9faf545b](https://github.com/srbhr/Resume-Matcher/tree/63fc344a9a59a79db6fa9d96aff188dc9faf545b). Its package version is 1.3.0. Context7's available fork did not document these endpoints, so the contract was verified from the actual upstream source. The pipeline's synthetic HTTP integration tests assert request payloads and exercise the complete sequence, recovery and PDF gates. **Live model inference, a running installed OpenAPI schema, container build/rendering, visual review of the chosen template, and real candidate content remain unverified.** Importing the upstream schema in the pipeline environment failed because FastAPI is absent; the upstream backend requires Python 3.13, while the pipeline runs Python 3.12. No upstream dependencies or services were installed for these tests.

## Exact endpoint sequence

All routes start with `/api/v1`. The source references are [resume routes](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/apps/backend/app/routers/resumes.py), [job routes](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/apps/backend/app/routers/jobs.py), and [schemas](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/apps/backend/app/schemas/models.py).

1. Read `GET /config/llm-api-key` and `GET /config/language` to fingerprint the configured provider, model, API base, reasoning effort and content language. Exclude the masked API key from keys and disk metadata. English content is required by the current validation rules. These are read-only requests; an unavailable provider configuration prevents generating or reusing an artifact rather than silently assuming it is unchanged.
2. `POST /resumes/upload` uses multipart field `file`, a deterministic `pipeline-master-{hash}.pdf` or `.docx` filename and the matching MIME type. Response contains `resume_id`, `processing_status` and master flags. Upload is capped locally at 10 MB. When a profile supplies `master_resume_id`, upload is skipped and the fetched structured content is included in the generation fingerprint.
3. Poll `GET /resumes?resume_id={id}`. Its response is `{request_id, data: {resume_id, raw_resume: {processing_status, content, ...}, processed_resume, parent_id, is_master, ...}}`. Require `ready`, structured content, `is_master=true`, candidate contacts, protected values and profile-supported skill lists. An upload with failed parsing is retained for inspection rather than automatically replaced.
4. `POST /jobs/upload` sends `{"job_descriptions": ["the source job description"], "resume_id": "master-id"}`. Response `job_id` is an array; exactly one ID is required. Job descriptions remain untrusted matching data. No candidate instruction text is appended to them.
5. `POST /resumes/improve` sends `{"resume_id": "master-id", "job_id": "job-id", "prompt_id": "keywords", "max_bullets_per_entry": 4, "page_fit": {"template": "swiss-single", "pageSize": "A4"}}`. Its `data.resume_id` is the saved tailored ID. This is the persisted endpoint; `/improve/preview` has a null resume ID. Fetch the saved structured resume and verify its `parent_id` and `GET /resumes/{id}/job-description` job ID before validation.
6. `GET /resumes/{id}/pdf?template=swiss-single&pageSize=A4` requires `application/pdf` and a readable PDF. The renderer uses headless Chromium against the frontend print route. Template/layout defaults are pinned in `GENERATION_CONFIG` and included in the generation key.

The inspected routes have no request authentication dependency. Use a private service network or loopback endpoint; the client does not implement a reverse-proxy authentication scheme. It disables redirects and environment proxy discovery. HTTP response bodies are never included in error messages. Responses are bounded at 16 MB. Known source errors include 400 empty/invalid input, 404 absent IDs, 413 excessive input, 422 unparseable upload, 500 failed improvement, and 503 busy database or PDF renderer. Socket timeouts are bounded by both `request_timeout_seconds` and the remaining generation budget. Polling and streamed chunks check the budget; an already-blocked socket operation can overrun the elapsed budget by at most one bounded operation timeout. The independent worker process/lease supervisor provides the operational recovery boundary.

## Crash recovery and reuse

`ResumeService(settings).generate(job, match, profile, checkpoint=None)` returns the shared `ResumeArtifact`. A supplied checkpoint dictionary is updated in place after each step. The authoritative checkpoint is private, atomic, fsynced JSON under `artifact_dir/.checkpoints/{generation_key}.json`; a separate `master-{hash}.json` caches the master across jobs. Nonblocking OS locks prevent concurrent generation of the same key and concurrent upload of the same master. One service/client instance belongs to one worker execution thread.

The generation key covers canonical job ID, exact description, candidate profile revision, master file bytes or fetched remote content, role family, matched fact IDs, backend address, chosen template/prompt/bullet/page settings, upstream source revision, validation revision and upstream model configuration. Artifact manifests contain generation/configuration identity, profile revision, selected match fact IDs, remote IDs, PDF SHA-256, review status and the serialized artifact. Reuse requires a matching manifest, expected local path and PDF checksum. A missing/corrupt PDF or manifest is repaired by downloading the saved remote resume, without another upload or LLM request. A corrupt checkpoint requires inspection because its missing IDs may conceal earlier remote writes.

Before every remote creation request, write `pending=master`, `pending=job` or `pending=tailor`; save its returned ID before clearing pending. Restart recovery behaves as follows:

- A pending master is reconciled through `GET /resumes/list?include_master=true` by the deterministic filename. Exactly one master must match.
- A pending tailor is reconciled through the list's `parent_id` and each candidate's `/job-description` job ID. Exactly one tailored draft must match. No match can mean inference is still running, so it is never treated as permission to repeat the request.
- A pending job upload cannot be reconciled automatically: the inspected API has no job list or idempotency key. Raise `ResumeReconciliationRequired`; retain the opening alert and leave generation needing attention. After verifying the upstream database, an operator may put the correct `job_id` into the disk checkpoint and remove `pending`. Never clear pending merely because a request timed out.
- A known 4xx rejection clears pending; a transport failure, malformed success response, 408/429 or server error conservatively retains it. Normal GET/download retries retain all known creation IDs.

`ResumeMatcherError` exposes `retryable` and `ambiguous` flags. `ResumeReconciliationRequired` and `ResumeValidationError` should be terminal needing-attention states in orchestration, with explicit retry only after investigation. Do not delete checkpoints as a generic retry operation.

## Factual and PDF guarantees

Structural validation rejects missing/malformed data, changed contact fields, new or changed standard experience employer/title/date identities, education institution/degree/date identities, project name/role/date/link identities, repeated invented rows and missing protected factual values. Original rows may be selected as a subset; protected values cannot disappear. Explicit skill claims outside factual profile skills, new certifications/languages/awards, new numerical claims and changed custom sections are flagged for review. The profile's stable fact IDs are checked and saved. Upstream accepts a master/job pair rather than a fact-ID selection payload, so role-family/matched-fact views are provenance and cache inputs; actual bullet/project selection is performed by the upstream harness from the description. An explicit pipeline-owned role-view projection is not implemented.

PDF validation rejects non-PDF downloads, malformed/encrypted files, empty or unreadable pages, excess pages, missing contacts/protected values, missing populated section headings, missing standard identity fields/skills and omitted experience/project descriptions. User-defined standard section headings are read from upstream `sectionMeta`. Text origins beyond page bounds produce a visual-review warning. Extraction cannot establish that text does not overlap or that its ink is not clipped, so visual template validation remains a live acceptance gate.

Every artifact includes an explicit **semantic grounding is unverified** warning and manifest `status=review_needed`. These automated checks do not prove rewrites preserve meaning or cover every skill mentioned in prose/custom sections. Review-needed PDFs may be sent as drafts with warnings; protected structural violations and unreadable PDFs are never returned as usable artifacts.

The upstream `/improve` implementation auto-creates a tracker application with `status="applied"`. **This is not evidence of application submission.** ResumeService never reads or changes pipeline `applied_at`; only the pipeline's explicit mark-applied workflow owns that field.

## Deployment pin

The upstream [README](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/README.md), [Dockerfile](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/Dockerfile), and [Compose file](https://github.com/srbhr/Resume-Matcher/blob/63fc344a9a59a79db6fa9d96aff188dc9faf545b/docker-compose.yml) describe a unified frontend/backend container on port 3000. Build the exact tested source contract, rather than assuming the mutable published `1.3.0` tag maps to this commit:

```yaml
resume-matcher:
  image: internship-resume-matcher:63fc344a9a59a79db6fa9d96aff188dc9faf545b
  build:
    context: https://github.com/srbhr/Resume-Matcher.git#63fc344a9a59a79db6fa9d96aff188dc9faf545b
    dockerfile: Dockerfile
  environment:
    FRONTEND_BASE_URL: http://localhost:3000
  volumes:
    - resume-data:/app/backend/data
```

Pipeline URL inside Compose is `http://resume-matcher:3000`; local URL is `http://localhost:3000`. Supply LLM settings/credentials through the supported upstream environment or private settings UI. Keep the image's frontend and Chromium dependencies together. After a successful build, record the built immutable image digest and verify `/api/v1/health`, installed `/docs`, the synthetic import/job/improve/PDF sequence, and a representative template image. No image digest or successful container build is claimed by this source-only pin.

## Focused verification

`PYTHONPATH=src <pipeline-venv>/bin/pytest -q tests/test_resumes.py` exercises synthetic data only. The suite covers complete endpoint payloads, checkpoints/manifests/cache, master reuse, lost mutation responses, ambiguous-job holds, download retry, corrupted artifacts, provider/master fingerprint changes, parsing timeouts, redacted errors, unsupported facts, structural factual mutations, numerical/skill review warnings, malformed schema and PDF readability/content/page/overflow checks. Ruff and mypy cover the owned runtime modules. No notification, application, external account action or live model call occurs in these tests.
