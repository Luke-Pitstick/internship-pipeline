# T10 — Reviewed PDF/DOCX/TeX resume import

Implemented October 6, 2026; corrected October 11, 2026. Settings → Profile provides authenticated PDF/DOCX/TeX upload that fills the existing editable profile form. The owner reviews or corrects those fields and chooses the ordinary Save changes action to save an immutable profile revision. Settings → Resume Generation also mounts T11's independent master-resume component with the current saved revision and unsaved-draft guard.

## User flow and factual boundary

The upload accepts a nonempty PDF or DOCX of at most 5 MiB. The existing `pypdf` dependency and maintained `python-docx` 1.2 parser extract text in a separate process. There is no model call, credential access, document execution, uploaded-template compilation, or external upload. PDF/DOCX binaries are discarded after extraction; SQLite retains the document hash, format, extracted source lines and locations, original profile revision, and confirmed field-to-source evidence.

The extractor selects literal names/email excerpts, experience/project claims under recognized headings, delimited acquired skills, and school/degree pairs readable on one or adjacent source lines. Skills with labels such as `Languages: Python, SQL` become the literal `Python` and `SQL` terms. Unrecognized sections, interests, and uncertain content remain excluded. Selection is bounded by remaining profile capacity, and the server rejects invented source excerpts and skills. Eligibility, availability and graduation dates are preserved as saved; absent information stays unknown and can be entered manually in the profile editor.

Choosing Fill profile from resume extracts and validates the selected source fields, then puts the proposed values directly into the existing Name, Email, facts/skills and Education controls. No separate source-field editor or preview screen replaces the form. All profile controls remain editable after file selection, extraction failure, and successful autofill. Extracted text is available in a collapsed disclosure for reference. Nothing is saved until the owner chooses Save changes; Discard changes restores the saved profile and clears the pending import.

Unsaved profile/filter edits must be saved or discarded before another import, so autofill cannot overwrite them. Manual edits made while extraction is running are preserved and block the late autofill; discarded or unmounted imports cannot later repopulate the form. Filled drafts survive category changes and warn before leaving the settings page. A concurrent profile save causes HTTP 409, preserves the local form and offers reload. Drafts expire after 24 hours; uploads purge expired drafts and retain at most ten pending drafts.

Replacement adds extracted claims while preserving existing facts and stable IDs. Old entries can be edited or removed in the ordinary form. Saving submits the reviewed form together with the original source selections to the import confirmation endpoint. Unchanged extracted values retain source provenance; owner corrections and additions are saved as manual facts without falsely attributing them to the document. The server revalidates source selections and revision before atomically saving the edited settings and matching provenance.

`ProfileSettings.save` has one narrowly scoped optional `record_import(connection, revision)` callback. The profile revision insertion and import approval/provenance update share the existing SQLite transaction; stale saves reject before the callback, and either write failing rolls both back. Imported confirmations use the ordinary profile revision mechanism, so candidate fingerprints and T06 assessment identities change and obsolete matching results cannot become fresh decisions.

## Processing and private API boundary

The extractor has a 12-second parent deadline, eight CPU seconds, one active process per application process, zero file-output allowance, and a 512 MiB address-space limit on Linux. Parser subprocesses use Python isolated mode and the extractor's absolute script path, so server `sys.path` setup and environment `PYTHONPATH` do not affect operation. PDF input is limited to 30 pages and 2 MiB decoded page content. DOCX archives are limited to 512 parts, 20 MiB expanded content, and a 100× per-part compression ratio. Duplicate parts, encrypted archives, macros, embedded objects and XML entity declarations are rejected. Extracted content is limited to 100,000 characters, 500 source lines and 2,000 characters per line; child output is bounded. Image-only, empty, malformed, encrypted and unsupported documents receive application-authored recovery messages. Parser logs and stderr are suppressed; request validation does not echo document content.

All routes reuse the owner-session/CSRF dependency, deny cross-origin mutations, and return `Cache-Control: no-store`:

- `POST /api/resume-imports/upload?format=pdf|docx|tex&expected_revision=N` accepts a raw binary body, capped at 5 MiB both at the shared application boundary and import service.
- `POST /api/resume-imports/{id}/preview` validates selections/removals and returns the saved and proposed profile alongside source evidence.
- `POST /api/resume-imports/{id}/confirm` requires the same revision and explicit `confirmed: true`. The ordinary form save also supplies `settings` containing the reviewed profile and preferences; only evidence matching the final values is retained. Profile and provenance save atomically.
- `GET /api/resume-imports/current` returns the last approved extracted source and provenance only to the authenticated owner. Preview/confirmation JSON bodies are capped at 256 KiB.

The parser APIs were checked through Context7 against official [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [pypdf streaming](https://pypdf.readthedocs.io/en/stable/user/streaming-data.html), and [python-docx container iteration](https://github.com/python-openxml/python-docx/blob/master/src/docx/blkcntnr.py). PDF decoding remains inside the isolated resource-limited child; decoded-size checks do not replace the Linux memory limit. The Linux memory-limit behavior was not exercised inside Docker on this macOS host.

## Acceptance audit and evidence

| T10 criterion | Completion evidence |
| --- | --- |
| Bounded PDF/DOCX with clear unsupported/encrypted/image-only feedback | Real PDF/DOCX extraction; encrypted, image-only, wrong type, oversized upload, 31-page PDF, decoded-page content, text/line bounds, archive size/part/ratio/duplicate/encryption/macro/entity tests; timeout/concurrency tests. |
| Existing PDF tooling, maintained DOCX parser; assistance only when needed | Reuses `pypdf`; `python-docx` dependency and locked `lxml`; deterministic literal draft needs no LLM assistance or new credential path. |
| Review important inferred fields, provenance, absent facts remain absent | Prepopulated source draft, exact-excerpt validation, explicit preview/checkbox/save, nullable eligibility and graduation dates; provenance/restart and no-invented-skills tests. |
| Replacement preserves manual confirmed additions and fills the editable form | Existing entries and IDs are preserved during autofill; the owner can remove or edit entries in the form, with accurate provenance and preserved preferences; Python and real Chromium replacement tests. |
| Saved revisions invalidate matching through shared mechanism | Atomic profile/provenance revision save; candidate fingerprint and T06 `current_identity` invalidation test; stale-review, rollback and stale callback tests. |

October 11 correction verification: the browser regression first failed on the actual symptom (`Name` remained empty after upload). After the change, the focused import/profile Python suite passed **51 tests**, including owner corrections/removals, accurate retained provenance, and unconfirmed/stale save rejection. Svelte check reports zero errors/warnings; the production build, focused Ruff and mypy checks pass.

Real Chromium against built Svelte and temporary FastAPI/SQLite passed profile/model regressions and the two autofill flows: filled editable contact/education/skill controls, no save until Save changes, edited name persistence, invalid-file recovery with editable availability, manual-fact and preference preservation, stable IDs, replacement/removal, PDF autofill, stale-save rejection/reload, mobile overflow and discard. The complete guided setup browser test also passed with the new fill → review/edit → Save changes flow. Tests use synthetic documents and temporary databases; these checks do not update the installed container or claim live personal-data acceptance.

Reproduce from the project root:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_resume_import.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/profiles src/internship_pipeline/profile_settings.py tests/test_resume_import.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m mypy src/internship_pipeline/profiles src/internship_pipeline/profile_settings.py
```

From `web/`, run `rtk npm run check`, `rtk npm run build`, and `rtk proxy npx playwright test tests/models.spec.ts tests/profile.spec.ts tests/resume-import.spec.ts --output=test-results/import-regression`. Browser fixtures require localhost binding permission. The temporary space-free virtualenv path is a local verification convenience; use the project's synced environment elsewhere.

The original T10 implementation was accepted October 6; the October 11 correction replaces its separate review-screen flow with the editable autofill flow described above. OCR/image-only import is intentionally unsupported with explicit feedback, as allowed by T10. Master document rendering is T11; job-specific model tailoring is T12; coordinated backup/restore packaging is T17. Those separate capabilities are not claimed by import. No live provider call, real profile read, external notification, commit, push, deployment or `.env` edit occurred. Shared whole-tree regression and Docker runtime validation remain parent/release verification gates; this document claims the focused and browser checks actually run.

## October 11 — TeX source imports

The file picker and API also accept UTF-8 `.tex` documents, capped at 100,000 characters with required document delimiters. `pylatexenc` reads body text without executing TeX or reading external inputs; ordinary reviewed profile save/provenance rules still apply. Source is kept privately in SQLite `resume_templates`. Only confirming the import activates that template for T12 AI tailoring. Preview and discard cannot activate it; a subsequently reviewed PDF/DOCX import chooses the application template again. The original uploaded source is preserved independently of each tailored draft. See [T12 source-first generation](t12-tailored-resumes.md#october-11--source-first-tex-tailoring) for rendering and verification.
