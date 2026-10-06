# T10 — Reviewed PDF/DOCX resume import

Implemented October 6, 2026. Settings → Profile now provides authenticated upload/replacement, a prepopulated source review, a before/after preview, and an explicit confirmation that saves an immutable profile revision. Settings → Resume Generation also mounts T11's independent master-resume component with the current saved revision and unsaved-draft guard.

## User flow and factual boundary

The upload accepts a nonempty PDF or DOCX of at most 5 MiB. The existing `pypdf` dependency and maintained `python-docx` 1.2 parser extract text in a separate process. There is no model call, credential access, document execution, uploaded-template compilation, or external upload. The binary is discarded after extraction; SQLite retains the document hash, format, extracted source lines and locations, original profile revision, and confirmed field-to-source evidence.

The draft preselects literal names/email excerpts, experience/project claims under recognized headings, delimited acquired skills, and school/degree pairs readable on one or adjacent source lines. Skills with labels such as `Languages: Python, SQL` become the literal `Python` and `SQL` terms. Unrecognized sections, interests, and uncertain content remain unselected. Preselection is bounded by remaining profile capacity. The owner can exclude a claim, change its field, and select exact source excerpts for contact/education or skills. The server rejects invented excerpts and skills. Eligibility, availability and graduation dates are preserved as saved; absent information stays unknown and can be confirmed manually in the profile editor. A checkbox and the separate confirmation action are required after preview.

Import review does not overwrite an unsaved profile/filter draft. Save or discard those edits first; while an import is being reviewed, the manual profile/filter editor is disabled. Category changes preserve the review, and navigation warns about unsaved imports. Cancellation restores the manual editor. A concurrent profile save causes HTTP 409, keeps the conflicting review visible, and provides an explicit reload/reupload action. Drafts expire after 24 hours; uploads purge expired drafts and retain at most ten pending drafts.

Replacement adds reviewed claims while preserving existing facts and stable IDs. Only unchanged facts/education with recorded import provenance are offered for removal; manually added and edited entries are protected. The preview shows contact changes, added claims/education and selected removals before confirmation. Deterministic imported IDs make preview and confirmation identical. Duplicate existing facts retain their current IDs and status rather than being overwritten.

`ProfileSettings.save` has one narrowly scoped optional `record_import(connection, revision)` callback. The profile revision insertion and import approval/provenance update share the existing SQLite transaction; stale saves reject before the callback, and either write failing rolls both back. Imported confirmations use the ordinary profile revision mechanism, so candidate fingerprints and T06 assessment identities change and obsolete matching results cannot become fresh decisions.

## Processing and private API boundary

The extractor has a 12-second parent deadline, eight CPU seconds, one active process per application process, zero file-output allowance, and a 512 MiB address-space limit on Linux. Parser subprocesses use Python isolated mode and the extractor's absolute script path, so server `sys.path` setup and environment `PYTHONPATH` do not affect operation. PDF input is limited to 30 pages and 2 MiB decoded page content. DOCX archives are limited to 512 parts, 20 MiB expanded content, and a 100× per-part compression ratio. Duplicate parts, encrypted archives, macros, embedded objects and XML entity declarations are rejected. Extracted content is limited to 100,000 characters, 500 source lines and 2,000 characters per line; child output is bounded. Image-only, empty, malformed, encrypted and unsupported documents receive application-authored recovery messages. Parser logs and stderr are suppressed; request validation does not echo document content.

All routes reuse the owner-session/CSRF dependency, deny cross-origin mutations, and return `Cache-Control: no-store`:

- `POST /api/resume-imports/upload?format=pdf|docx&expected_revision=N` accepts a raw binary body, capped at 5 MiB both at the shared application boundary and import service.
- `POST /api/resume-imports/{id}/preview` validates selections/removals and returns the saved and proposed profile alongside source evidence.
- `POST /api/resume-imports/{id}/confirm` requires the same revision and explicit `confirmed: true`, then atomically saves the profile and provenance.
- `GET /api/resume-imports/current` returns the last approved extracted source and provenance only to the authenticated owner. Preview/confirmation JSON bodies are capped at 256 KiB.

The parser APIs were checked through Context7 against official [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [pypdf streaming](https://pypdf.readthedocs.io/en/stable/user/streaming-data.html), and [python-docx container iteration](https://github.com/python-openxml/python-docx/blob/master/src/docx/blkcntnr.py). PDF decoding remains inside the isolated resource-limited child; decoded-size checks do not replace the Linux memory limit. The Linux memory-limit behavior was not exercised inside Docker on this macOS host.

## Acceptance audit and evidence

| T10 criterion | Completion evidence |
| --- | --- |
| Bounded PDF/DOCX with clear unsupported/encrypted/image-only feedback | Real PDF/DOCX extraction; encrypted, image-only, wrong type, oversized upload, 31-page PDF, decoded-page content, text/line bounds, archive size/part/ratio/duplicate/encryption/macro/entity tests; timeout/concurrency tests. |
| Existing PDF tooling, maintained DOCX parser; assistance only when needed | Reuses `pypdf`; `python-docx` dependency and locked `lxml`; deterministic literal draft needs no LLM assistance or new credential path. |
| Review important inferred fields, provenance, absent facts remain absent | Prepopulated source draft, exact-excerpt validation, explicit preview/checkbox/save, nullable eligibility and graduation dates; provenance/restart and no-invented-skills tests. |
| Replacement preserves manual confirmed additions and previews changes | Imported-only removal permissions, edited-fact protection, stable preview/save IDs, preferences preserved; Python and real Chromium replacement tests. |
| Saved revisions invalidate matching through shared mechanism | Atomic profile/provenance revision save; candidate fingerprint and T06 `current_identity` invalidation test; stale-review, rollback and stale callback tests. |

Focused Python verification: **35 tests passed** in `tests/test_resume_import.py`. A preceding combined import/profile run passed **41 tests** before additional resource/capacity/invalidation coverage was added. Focused Ruff passes and mypy passes all four profile/import source files. The only Python warning is the existing Starlette/httpx TestClient deprecation.

The real Chromium import flow passed against built Svelte and temporary FastAPI/SQLite: invalid-file recovery, DOCX upload, useful preselection including education/skills, source review, preview, explicit save, reload/stable IDs, dirty-draft guard, replacement/removal, manual fact and preference preservation, PDF upload, concurrent-save conflict/reload and cancellation. A subsequent combined model/profile/import regression run passed **three tests**. It uses synthetic committed PDF/DOCX fixtures and does not mock extraction or profile persistence. The 390px mobile screenshot (`web/test-results/t10-resume-import-mobile.png`, ignored) was inspected and the browser verified no horizontal overflow. Svelte check reports zero errors/warnings and the production build passes with both import and master-resume settings panels mounted.

Reproduce from the project root:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_resume_import.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/profiles src/internship_pipeline/profile_settings.py tests/test_resume_import.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m mypy src/internship_pipeline/profiles src/internship_pipeline/profile_settings.py
```

From `web/`, run `rtk npm run check`, `rtk npm run build`, and `rtk proxy npx playwright test tests/models.spec.ts tests/profile.spec.ts tests/resume-import.spec.ts --output=test-results/import-regression`. Browser fixtures require localhost binding permission. The temporary space-free virtualenv path is a local verification convenience; use the project's synced environment elsewhere.

No T10 acceptance requirement is left open. OCR/image-only import is intentionally unsupported with explicit feedback, as allowed by T10. Master document rendering is T11; job-specific model tailoring is T12; coordinated backup/restore packaging is T17. Those separate capabilities are not claimed by import. No live provider call, real profile read, external notification, commit, push, deployment or `.env` edit occurred. Shared whole-tree regression and Docker runtime validation remain parent/release verification gates; this document claims the focused and browser checks actually run.
