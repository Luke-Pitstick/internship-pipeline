# ChatGPT plan connection implementation

Prepared October 19, 2026. Scope: an optional ChatGPT plan connection for the
open-source, single-owner pipeline, alongside the existing API-key providers.
Pipeline sign-in, collection, notifications, and fact-grounding rules retain
their existing responsibilities. No deployment or paid model request is part of
implementation verification.

## Supported contract

Primary sources checked October 19, 2026:

- [Overview](https://developers.openai.com/siwc/token-sharing-open-source)
- [Registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [UI requirements](https://developers.openai.com/siwc/ui-ux-guidelines)

Use dynamic public-client registration, a stable per-installation host UUID,
Authorization Code + S256 PKCE, state and nonce. Request `openid profile email
offline_access resource.invoke chatgpt.tokens.use.direct`, with
`resource=https://api.openai.com/v1`. Persist the issued client ID, never
`dynamic_agent_client`. Authorize/token endpoints are under
`https://auth.openai.com/api/accounts/`. Validate ID tokens against OpenAI's
published keys, fixed issuer, issued audience, expiry, nonce and subject.

Inference uses the public Responses endpoint, OAuth bearer credentials,
`store:false`, `stream:true`, array input, and account-specific model discovery.
Do not transmit unsupported `max_output_tokens`. A completed stream and locally
validated structured output are required for success. No private ChatGPT or
Codex inference endpoints, copied Codex credentials, automatic provider fallback,
or access to ChatGPT conversations is involved.

## Implementation sequence and acceptance gates

### 1. Persist registrations and OAuth transactions

- Add a small ChatGPT module using the existing SQLite database and instance
  Fernet key. Store encrypted token bundles separately from immutable model
  configuration revisions; refresh never creates a model revision.
- Keep account registrations separate by verified issuer/subject/client ID;
  show safe account labels and allow choosing a saved registration.
- Persist the host ID once. Store expiring, single-use pending authorizations,
  binding expected model revision, state, nonce, verifier, redirect URI and any
  returning registration. Cancelled/invalid callbacks cannot replace accounts.
- Use PyJWT for JWT/JWK verification, fixed OpenAI endpoints, bounded HTTP, safe
  errors and no request-body/token logging.
- Serialize rotating-token refresh across processes without holding a SQLite
  write transaction over a network request; atomically replace token bundles.
- Revoke refresh sessions before clearing credentials, reporting unconfirmed
  remote revocation explicitly. Deleting a selected registration invalidates
  the current model connection.
- Gate: signed synthetic JWTs exercise issuer/audience/nonce/signature/scope
  failures, callback replay, revision races, restart persistence, refresh races,
  encryption, token redaction and disconnect behavior.

### 2. Connect locally and from remote installations

- Owner/CSRF-protected start, status, models, account-selection and disconnect
  APIs. For an HTTP loopback pipeline origin, use a `127.0.0.1` callback on its
  published port, including when Docker maps the application port.
- The callback uses the pending OAuth state rather than requiring a cross-site
  owner cookie. Return a static result page with no scripts or reflected query
  data, and direct the owner back to the configured application origin.
- For HTTPS/remote installations, provide a downloadable standard-library
  Python helper. An owner creates a short-lived one-use pairing code; the helper
  binds a local `127.0.0.1` listener, claims the pairing transaction, completes
  OAuth and token exchange locally, and transfers the token response to the
  intended pipeline over HTTPS (HTTP only for loopback). The server validates
  identity/permissions before encrypting it. No tokens travel in URLs or browser
  storage. Pairing routes require the transaction secret, have strict size and
  expiry bounds, and cannot select arbitrary upstream hosts.
- Gate: API authorization/CSRF, hostile origin/host, local callback, helper
  callback state/error/timeout handling, single-use pairing, remote identity
  validation, cancellation, and safe redirects tested with synthetic transports.

### 3. Integrate inference and connection readiness

- Add explicit `auth_mode` and optional ChatGPT registration ID to the existing
  general model configuration. API-key providers keep their current contracts;
  ChatGPT credentials resolve through the account store for tests and workers.
- Discover visible account models and validate the selected model server-side.
- Share bounded provider response reading between connection probes and resume
  generation. Use a maintained SSE decoder, reject missing completion, refused,
  failed, incomplete, malformed or oversized responses, and normalize usage.
- Preserve current revision checks, synthetic capability-test admission,
  confirmed-fact validation, source-edit restrictions and worker isolation.
- Record that ChatGPT provides no server-side output-token cap; retain byte and
  wall-clock bounds and show plan usage controls instead of claiming a token cap.
- Gate: probe and resume paths consume realistic SSE, including subscription
  failures after HTTP 200 and partial deltas, and reject unsupported facts.

### 4. Build the settings experience

- Add a ChatGPT plan choice to general AI settings and connect/reconnect,
  saved-account picker, account models, explicit save/test, disconnect and status.
- Show a dismissible welcome confirmation once per registration, a persistent
  “Using ChatGPT plan” indication and Manage usage link, and actionable consent,
  expiry/reconnect and usage-limit errors. Explain shared ChatGPT allowance.
- Provide remote helper download/run/pair instructions only for installations
  that need them. Do not expose tokens or implementation details in normal flows.
- Gate: Svelte/TypeScript check and build plus browser tests covering connection
  states, save/test readiness, remote instructions, errors and narrow layouts.

### 5. Review and record evidence

- Run focused Python regressions while implementing, then the full Python suite
  once, Ruff, relevant mypy checks, frontend check/build and focused browser QA.
- Review standards and this plan against the task-owned diff; fix actionable
  findings and repeat only affected checks.
- Update this checklist with actual results and document local versus remote
  setup, shared limits, preview constraints and credential backup/recovery.
- Commit only the ChatGPT implementation and its owned docs/tests. Preserve the
  pre-existing installer/account-recovery changes; do not push or deploy.
- Live acceptance remains explicitly pending until a user completes official
  ChatGPT consent and authorizes a real synthetic probe/resume request. Mocked
  OAuth/JWT/SSE verification never counts as credentialed provider acceptance.

## Progress

- [x] Read current provider/settings/owner boundaries and primary OpenAI docs.
- [x] Record the implementation sequence before editing runtime code.
- [x] Registration, persistence, refresh and disconnect.
- [x] Owner routes, loopback callback and remote helper.
- [x] Streaming inference, model discovery and worker integration.
- [x] Settings UI and browser verification.
- [x] Run full checks, complete review, prepare the scoped commit and record evidence.

## Completion evidence

Implemented in source on October 19, 2026. User setup and operational boundaries
are in [Use your ChatGPT plan](chatgpt-plan.md). Storage format is now 2 because
the persisted authentication configuration is incompatible with format 1 readers;
OAuth account and pending-authorization ciphertext is checked during backup
verification. No migration, deployment, live account connection or release was
performed.

- Final focused Python run: **163 passed**, covering accounts/JWT/OAuth,
  concurrent refresh and reauthorization, helper transfer, bounded SSE, existing
  providers, owner configuration, durable résumé work, backup and storage-format
  behavior. The worker regression resolves encrypted ChatGPT credentials from
  the saved connection, consumes synthetic SSE, and generates a real local PDF
  from confirmed synthetic facts. No model service was contacted.
- Isolated Chromium suite: **2 passed** through the authenticated owner API,
  using mocked ChatGPT routes. Covers remote pairing instructions, account/model
  selection, first-use confirmation, usage limits, capability feedback,
  two-account discard/reload, disconnect, local sign-in popup/cancel and 390px
  overflow checks. Desktop/mobile screenshots were inspected. Run with
  `cd web && npx playwright test --config playwright.chatgpt.config.ts`; its port
  and ignored artifacts are isolated from concurrent browser suites.
- Existing provider browser suite also passed before concurrent settings edits
  (three combined checks passed). A later combined run encountered settings
  navigation changes and shared-artifact interference. The final isolated
  ChatGPT suite uses the supported AI Models bookmark to test this feature.
- Svelte check: **0 errors, 0 warnings**; production frontend build passed.
  Scoped Ruff, mypy (**12 source files**) and diff whitespace checks passed.
- Full Python suite was run once: **1,182 passed, 2 failed** in 240.59 seconds.
  Both failures were the Docker/Podman variants of the unrelated management
  missing-installation wording assertion during concurrent installer changes.
  A targeted rerun while that work continued reached a new, unrelated
  `pipeline_release` import failure. This is not a fully green whole-checkout
  acceptance claim; the final 163-test task regression is green.
- Independent standards/security and specification reviews identified four
  defects: pending-authorization key preservation, unbounded revocation reads,
  OAuth reconnect messaging and stale account-model options. All were corrected;
  follow-up reviews confirmed the fixes with no remaining actionable findings.
  Reauthorization was also serialized with refresh/disconnect and race-tested.

Live acceptance remains open: an eligible real account must complete OpenAI's
official consent and run the explicit synthetic capability test, then a grounded
résumé request. Offline evidence does not establish account availability, exact
schema support on a real model, hosted-container behavior or public release.
