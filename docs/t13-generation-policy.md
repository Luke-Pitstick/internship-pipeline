# T13 — automatic résumé generation policy

Implemented October 6, 2026. Settings → Resume Generation provides a durable, off-by-default
automatic draft toggle, minimum rubric fit, recommendation rule and eligibility rule. Manual
generation remains available in each job. These settings create drafts independently of
search inclusion and email/Sheets rules; they never submit an application or enable automatic
rejection. Fit measures rubric alignment on a 0–100 scale, not interview probability.

## Rules, preview and persistence

The default rules require at least 75 fit, a recommended assessment and confirmed eligibility.
The owner may include review recommendations and explicitly allow unknown eligibility;
unknown stays unknown and every PDF remains a draft requiring review. Explicitly ineligible,
closed and applied jobs do not qualify. Only the current authoritative persisted Jev assessment
can qualify: posting, opening, profile, Jev configuration/model and rubric changes invalidate it.
No provider request is made to load or preview policy settings.

`generation_policy` stores the policy and optimistic revision in the shared SQLite database.
GET `/api/generation-policy` returns saved rules plus current qualifying/open counts;
POST `/api/generation-policy/preview` counts proposed rules without saving or queueing;
POST `/api/generation-policy` checks `expected_revision`, saves and reconciles work.
The authenticated API preserves existing owner, CSRF and same-origin mutation protection.
No candidate facts, model keys or private paths are exposed by the preview.

## Queue, races and idempotency

The existing tailored-resumes worker reconciles qualifying current jobs every 30 seconds.
It reuses T12's shared tasks queue and content/profile/model/template/grounding identity:
automatic and manual requests share the same task and artifact, and repeated scans or saves
cannot duplicate successful output or replay failed provider work. Turning off automation,
or tightening its rules, cancels pending automatic work in the policy save transaction.
Re-enabling qualifying cancelled work reuses its task; deliberate manual generation promotes
pending/cancelled work to manual origin and can explicitly retry failed work.

Policy is checked before enqueue and again inside the enqueue transaction, atomically inside
the queue claim transaction, and after claim immediately before provider-attempt admission.
A disable after claim but before provider I/O prevents the call and restores the unused
attempt budget. Claim checks also cancel work whose assessment became stale or whose job
closed or was applied. Manual work is unaffected by these generation-policy checks. A request
already started before a disable may finish its draft; disable prevents pending work from
starting and does not retroactively undo provider I/O. T12 revision/lease publication guards
still prevent stale output.

T08 run admission reserves conservative serialized request bytes plus the configured output
limit inside the provider-attempt transaction. Budget decline makes no HTTP request, creates
no tailored_attempt row and consumes no generation attempt; unknown reported usage retains
the reservation. Completed provider usage is recorded separately from generation policy.

## Verification and boundaries

Sixteen focused Python tests pass using current synthetic authoritative assessments and
mocked official-provider HTTP, including actual pdflatex generation. Coverage includes default
off/durable settings, read-only preview, all fit/recommendation/eligibility options, owner/CSRF
validation and revision conflicts, enqueue/claim policy guards, disable after claim before HTTP,
stale profile/Jev revisions, closed/applied jobs, manual promotion/unaffected work, concurrent
and repeated reconciliation/cache reuse, failed work without automatic replay and run-budget
decline without a consumed attempt. T12's 21 provider/compiler regression tests pass alongside
them. Focused Ruff and mypy pass; Svelte reports zero errors and warnings and the static
production build passes.

Reproduce with `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_generation_policy.py
 tests/test_tailored_resume.py`. After building `web/`, use `npx playwright test --config
playwright.generation-policy.config.ts`; its dedicated fixture binds loopback port 4191,
uses synthetic candidate data and mocked Jev/general HTTP with the real worker and compiler.
One dedicated Chromium browser test passed in 5.3 seconds. The browser checks default off, preview, save/reload persistence, automatic PDF generation,
disable persistence, manual action availability, authenticated PDF bytes and 390px Settings
layout without overflow. The Settings mobile screenshot was visually inspected; labels, controls and explanations are readable without clipping. Its private temporary fixture output is ignored.

No supported general-LLM credential was supplied, so T12's bounded real-provider generation
acceptance remains blocked pending an owner-supplied supported credential and explicit bounded
live inference authorization. Docker is unavailable, so native tests do not prove container
acceptance on T03. T16 owns complete guided onboarding; T17 owns complete backup/restore;
T21 owns independently adjudicated recommendation/rejection-quality and release acceptance.
No private candidate files, paid live inference, actual notifications, applications, commits,
pushes or deployments were used for this work.
