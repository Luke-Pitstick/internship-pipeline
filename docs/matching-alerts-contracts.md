# Matching and notification contracts

Implemented S4 and the notification portion of S6. All committed data is synthetic.
The coordinator owns persistence, content/profile cache keys, retries and per-destination
delivery idempotency. These modules do not modify job/application state or generate PDFs.

## Matching

`match_job(job: Job, profile: CandidateProfile, settings: Settings) -> MatchResult`
uses deterministic checks first. It recognizes SWE, product management, ML/AI and data
science variants, including ambiguous titles supported by their descriptions. Project
and program management remain outside product management. Explicit permanent/senior
roles do not become internships merely because their descriptions mention interns.

Only explicit conflicts with supplied constraints set `eligible=False`: known country
mismatch across all listed locations, an explicit season/year mismatch, mandatory degree
requirements above the supplied degree level, a stated graduation-year interval excluding
the supplied date, or explicit exclusion of sponsorship when sponsorship is required.
Remote or partly unknown locations, vague degree clauses, alternative equivalent
experience, absent requirements and absent candidate inputs stay visible as unknowns.
Cities without clear exclusive-location requirements remain questions to confirm;
authorization to work does not prove citizenship, and the candidate's positive
authorization list does not prove ineligibility elsewhere.

Without model configuration, plausible matches receive `possible`, supported skill/fact
references and a concrete explanation. This is a conservative relevance assessment,
not a prediction of interview odds or a full semantic qualification review. Unsupported
role evidence and explicit non-internships receive `weak` without invented eligibility
conflicts. Unknown internship status remains a visible question for a plausible role.

Set both `Settings.llm_base_url` (the API base, commonly ending in `/v1`) and
`llm_model` to enable one short OpenAI-compatible `POST /chat/completions` assessment.
`llm_api_key` supplies an optional Bearer header; local services may omit it.
Requests use the configured HTTP timeout, a 900-token output limit, temperature zero
and JSON response format. Providers must support these request fields. The packaged
`prompts/match.txt` puts instructions in the system message and treats all job/profile
payload text as untrusted data in the user message.

The response schema forbids extra fields and accepts only `strong`, `possible`, `weak`
and the four role families. Every candidate fact ID must exist in the supplied profile.
Every requirement, qualification-gap and unknown excerpt must occur in the posting
description (case/whitespace normalization allowed). An empty evidence list, fabricated
fact, contradictory role classification or unsupported strong fit is invalid. Model
eligibility decisions and percentages are not accepted. These checks establish evidence
provenance; they do not prove every semantic conclusion is correct.

Configured HTTP failures, malformed responses, unsupported evidence and incomplete
configuration raise `MatchAssessmentError`. It has `retryable=True` and a
`deterministic_result: MatchResult` containing the preliminary plausible assessment.
The coordinator must retain that assessment and retry the matching task; do not turn
provider failure into a negative fit or drop the opportunity. Hard conflicts and unsupported
roles skip model calls entirely. Failure messages omit provider responses and credentials.

## Notifications

Required signatures are unchanged:

```python
opening_message(job: Job, match: MatchResult) -> tuple[str, str]
resume_message(job: Job, artifact: ResumeArtifact) -> tuple[str, str]
send_notification(url: str, title: str, body: str, attachment: Path | None = None) -> bool
```

Opening text includes company/title, location, explicit term when available, fit evidence,
eligibility questions, qualification gaps, first observation, source timestamp and its
original `timestamp_kind`, last verification, deadline, compensation, stable job ID and
direct application URL. Missing details are labeled `Not supplied`. Backlog, updates and
reopenings have distinct titles; new observations do not claim new source publication.
Aware timestamps are rendered in UTC; naive timestamps are explicitly timezone-unspecified.

Resume text repeats the job ID/application URL, adds the artifact revision, creation time
and tailoring summary, and prominently shows review warnings. An artifact for another
job raises `ValueError`. The coordinator passes an already validated PDF as the separate
`attachment` argument. Neither message claims the pipeline submitted an application.

The transport lazily imports Apprise, registers one destination with `Apprise.add(url)`,
and sends plain text through `notify(title=..., body=..., attach=absolute_local_path)`.
It returns true only for an actual `True` result. Invalid URL registration, missing/empty
attachments, exceptions, `False` and `None` all return false. PDF sends additionally check
each plugin's `attachment_support`; unsupported services cannot count a text-only send
as PDF success. PDF validity/content checks belong to the resume service.

True means provider acceptance, not receipt/read confirmation. A timeout may be ambiguous
even when the function returns false; the coordinator retains/retries the delivery and
uses the stable reference to make possible duplicates recognizable. This helper does
not promise exactly-once delivery, redact Apprise's own internal logger, override service
size limits or independently enforce a total wall-clock send deadline. Service URLs may
have provider-specific timeout/retry settings; verify them with the chosen destination.

`record_notification(path: Path, title: str, body: str, attachment: Path | None = None)
-> bool` is an offline transport. It appends a JSONL event with `transport=recording`, title,
body, attachment path and recording time, without storing a destination URL. Success
means only that the event was written. The coordinator must distinguish recording events
from live delivery. Private alert content belongs in ignored local paths.

## Verification evidence

Apprise 1.13.1 is installed in the shared development environment. Its installed Python
signatures were inspected, including `add -> bool`, `notify -> bool | None`, indexed
service iteration and `NotifyBase.attachment_support`. Context7 documentation was
resolved as `/caronc/apprise` and checked against the installed API:
[development API](https://github.com/caronc/apprise/wiki/Development_API) and
[attachment examples](https://github.com/caronc/apprise/blob/master/README.md).

Focused synthetic tests cover labeled role families, project/product distinctions,
unknown eligibility, country/location ambiguity, season/year mismatches, mandatory
versus vague/negated/alternative degrees, graduation conflicts, prompt isolation,
unknown fact IDs/excerpts, malformed model output, HTTP failure/timeouts, distinct
timestamps, PDF delegation, invalid/unsupported attachments and delivery failure.
Ruff and strict mypy checks cover both production modules.

No live LLM request or destination message has been sent. Real provider compatibility,
destination credentials, attachment size limits and actual PDF delivery remain explicitly
unverified until the user supplies configuration and authorizes those integration checks.
