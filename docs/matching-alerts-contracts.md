# Matching and email transport contracts

Production decisions are authoritative persisted Jev assessments with immutable revisions,
evidence and a code-computed fit; see [T06 decisions](t06-jev-decisions.md). Automatic
rejection remains disabled. A score measures rubric alignment, never interview probability.
The matcher persists decisions without generating documents or enqueueing notifications.
Collection remains independent of matching, generation and integrations.

Optional SMTP alerts and digests are configured through authenticated Settings and owned by
[EmailIntegrations](t14-email-alerts.md), including encrypted credentials, delivery memberships,
bounded attempts, recorded acceptance and explicit review of uncertain outcomes. Email
qualifies current authoritative assessments independently of the draft-generation policy.
The obsolete arbitrary destination URLs, recording transport, Dot relay, opening-message
coordinator and `delivery` worker are removed. Sheets uses its independent
[preview and sync contract](t15-spreadsheet-sync.md).

Job-specific drafts are reviewed and downloaded through the authenticated T12 API.
Generation has no dependency on email delivery. [T13 policy](t13-generation-policy.md)
controls automatic drafts separately from search inclusion and integration rules.

## Retained Apprise SMTP transport

`email_integrations.apprise_email` builds the configured TLS SMTP URL from encrypted
Settings, lazily imports Apprise and returns `accepted`, `rejected` or `uncertain`.
Invalid destination registration is rejected before a send. Only an actual `True`
notification result is accepted; `False`, `None` and send exceptions are uncertain.
An unknown remote acknowledgement requires owner review and explicit retry.

Optional guarded PDF bytes are written privately to temporary files, passed to Apprise
only when its attachment contract is supported, then removed. An unsupported optional
attachment leaves the alert deliverable without it, matching the configured integration
semantics; it does not establish that a PDF was delivered. Master/tailored generation
and the email worker validate current PDFs before offering bytes to the transport.

Synthetic tests exercise the actual SMTP URL configuration, plain-text body, private
attachment content and cleanup, unsupported optional attachments, invalid registration,
False/None acceptance and timeout sanitization. Current integration tests exercise durable
membership, budgets, retries and uncertainty separately. The obsolete generic transport
and its recording helper are removed. No live destination was contacted for cleanup.
