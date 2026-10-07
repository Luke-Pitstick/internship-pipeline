# Cross-task integration cleanup — October 6, 2026

Status: complete for the T08/T12/T13/T14/T15/T17 shared-runtime cleanup. No commit,
publication, deployment, private candidate input, paid request, real email or remote Sheets
mutation occurred. Concurrent T16 onboarding and T18 container/release changes are preserved.

## Removed behavior

- Matching no longer accepts notification destinations or queues opening notifications.
  `Store.save_match` only persists a match and its event; accepted jobs remain unapplied.
  Pipeline drains matching work only, while authoritative Jev evaluation remains its production
  path. Generation policy, optional email and Sheets own their independent queues.
- Removed arbitrary `notification_urls`, its environment parsing, `dot_outbox_path` and
  `recording_notifications_path` from configuration and the example. Obsolete YAML fields are
  rejected by the existing strict Settings schema instead of becoming compatibility aliases.
- Removed the `delivery` CLI/supervisor role, destination prerequisite, legacy deliveries
  schema/helpers/latency metric, opening-message dispatch, generic notifications module,
  Dot outbox implementation, recording helper and synthetic CLI demo. Tests for those removed
  APIs were replaced with current matching independence and SMTP adapter regressions.
  T18 removed the obsolete CI demo invocation from its owned workflow.
- Audited source/tests/config for ResumeService, deleted résumé provider modules, old résumé
  worker dispatch and obsolete notification imports: none remain. Master/tailored generation,
  current authoritative assessment revisions, job state and shared queue identities are retained.
  No migration, fallback worker or second queue was added. Existing private SQLite files were
  neither inspected nor altered; removed code does not send or replay historical legacy work.
- Updated active integration/agent contracts and README. October 5 design/acceptance evidence
  remains explicitly historical and links to current contracts; it cannot certify removed
  demo/relay behavior as current product acceptance.

## Recovery and retained safeguards

The CLI now takes an exclusive offline installation lock for owner recovery and setup-token
rotation. Other app/worker runtime locks remain shared; backup remains exclusive. The owner
regression checks that recovery is rejected during an active app lifespan, succeeds after
shutdown, invalidates old sessions and preserves explicit Applied state. This fixes the shared
lock gap rather than weakening the protection to make a running-app recovery test pass.

The full backup fixture now stores current accepted and in-flight email ledger records instead
of the removed generic deliveries table. It verifies accepted timestamps survive, in-flight
email becomes uncertain and tasks require review. Existing encrypted credential/key, source
provenance, real compiled master/tailored PDF, completed Sheets journal and no-replay checks
are retained. Generic Diagnostics retries still exclude email and Sheets external side effects.

The actual SMTP Apprise adapter remains `email_integrations.apprise_email`. New direct-adapter
regressions verify encoded SMTP/TLS settings, private temporary attachment bytes and cleanup,
invalid registration, False/None/timeout uncertainty and unsupported optional attachments.
Email's current optional attachment semantics remain unchanged: an unsupported PDF may be
omitted while the plain-text alert is accepted, with no claim that a PDF was delivered.

## Verification

- Full combined Python regression suite: **514 passed**, one existing Starlette TestClient
  deprecation warning, **40.53 seconds**. Command: `rtk proxy env PYTHONPATH=src
  .venv/bin/pytest -q`. Native bootstrap/supervisor loopback tests required approved sandbox
  escalation. The earlier restricted run's loopback denial was environmental; the full
  escalated run passed the real process setup/restart/graceful-shutdown regression.
- Focused recovery/email/operations suite: **32 passed**, **9.58 seconds**, using actual
  SQLite, real local PDF compilation and mocked external providers/transports.
- Full source/tests Ruff checks pass, including the shared assessment import-format repair. Strict mypy
  passes all **55** source modules. `rtk git diff --check` passes.
- Literal source/tests/config audit leaves obsolete destination names only in rejection tests,
  and `delivery` only in the assertion that this old role is absent. Deleted runtime imports
  and the old opening latency query are absent.

## Remaining acceptance boundaries and ownership

There is no remaining cleanup implementation blocker. T16 owns the still-in-flight onboarding
implementation; its new browser journey and tests need its own final acceptance.
The final full source/tests Ruff check passes after its formatting repair. T18 owns Docker/CI/container portability and
fresh-volume interruption/restore acceptance; the Python/native process result does not
establish an actual image run. Deployment docs must describe the current configured roles.
T12/T14/T15 live general-model/SMTP/Google verification still requires owner-supplied inputs
and explicit bounded authorization, as recorded in their handoffs. No mocks are counted as
live provider or container evidence. The coordinator owns final all-repository checks after
concurrent workers finish and the shared completion tracker.
