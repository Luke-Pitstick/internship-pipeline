# T05 — Independent model connections

Implemented October 6, 2026. The authenticated **Settings → AI Models** panel saves, tests, edits, and removes independent Jev and general-LLM connections. Saving configuration does not contact a provider. T06 subsequently integrated tested Jev connections into matching; résumé generation remains T12 work. This document records the original T05 verification and the later follow-up evidence separately.

## Supported contracts and data flow

| Connection | Supported endpoint | Required response capabilities |
| --- | --- | --- |
| Jev | `https://api.typesafe.ai/v1/systemone` | TypeSafe Choice criterion and evidence-ID answers, Score distributions, confidence, effective model identity, input/output token usage. Default selected model is `jev-1.13.0`; users can edit it. |
| General LLM — OpenAI | `https://api.openai.com/v1/responses` | Responses with strict `text.format` JSON Schema, completed text message, effective model identity and input/output token usage. Requests set `store: false`. |
| General LLM — Claude (Anthropic) | `https://api.anthropic.com/v1/messages` | Messages with `output_config.format` JSON Schema, completed assistant text (`end_turn`), effective model identity and input/output token usage, including cache input usage. Uses `x-api-key` and the Anthropic version header. |
| General LLM — OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | Chat Completions with strict `response_format.json_schema`, completed assistant text (`stop`), effective model identity and prompt/completion token usage. Model IDs can include `provider/model`; routing requires parameter support and disables provider fallbacks. |

The October 8, 2026 provider extension supports these four official endpoints. General LLM models must support structured outputs. The saved endpoint identifies the provider, so no additional provider field or database migration is needed. The endpoint fields are visible and read-only; the server rejects every other URL, including userinfo, query strings, loopback addresses, proxies and unlisted providers. There is no claim of generic “OpenAI-compatible” support or automatic model fallback. Switching the general LLM provider requires an explicitly supplied key for that provider and creates a new untested revision; an existing key is retained only when editing the same provider.

The current tests transmit only application-owned synthetic facts. The Jev probe asks three typed questions about a synthetic candidate's Python skill and one synthetic posting: a four-outcome requirement choice, a closed-set evidence choice, and a four-level score. The general-LLM probe requests a structured fact and its fixed evidence identifier and validates the actual JSON response. None of the probes reads the user's profile or résumé. The UI explains that future matching sends confirmed candidate skills, experience, eligibility facts, preferences and job descriptions to Jev; future extraction/generation sends selected résumé text, confirmed facts and job context to the general LLM. Provider retention policies still apply; `store: false` applies to OpenAI and is not a promise of zero provider retention; Anthropic and OpenRouter use their own retention policies.

A passing probe checks connectivity and required response capabilities. It does **not** validate matching quality, factuality across real candidates, automatic rejection, or résumé quality. T02's automatic-rejection quality gate remains unmet.

API contracts were checked using Context7 against the official [TypeSafe API](https://docs.typesafe.ai/api), [Choice documentation](https://docs.typesafe.ai/primitives/choice), [TypeSafe quickstart](https://docs.typesafe.ai/introduction/quickstart), [OpenAI structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs), and [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create).

## Persistence and credential recovery

`ModelConnectionStore` creates three tables in the shared jobs SQLite database: `model_revisions` is an append-only configuration/deletion history; `model_credentials` holds only each current encrypted credential; `model_attempts` records test reservation, completion, status, effective model, actual usage or unknown usage, payload size, and supported output limit. Every save creates a new immutable revision and invalidates previous readiness. An optimistic `expected_revision` rejects stale edits/removals/tests. Results from an older in-flight request remain attached to that original revision and cannot mark a newer configuration ready. Removal deletes the active encrypted credential and appends a deletion revision, preserving audit metadata.

Credentials use authenticated Fernet encryption from the maintained `cryptography` package, following its [documented encryption/decryption contract](https://cryptography.io/en/latest/fernet/). They are never included in configuration reads, revision JSON, provider error messages, or test output. Blank edit fields omit the credential and retain the saved value; a supplied nonempty key replaces it. Password inputs clear immediately when a mutation starts, including on errors. Server validation rejects control characters and whitespace in keys and bounds all settings. The app's validation handler does not echo request inputs.

The generated instance encryption key is `<PIPELINE_DATA_DIR>/model-credentials.key`, mode `0600`. It stays in the persistent volume and is not served by an API. **Back up that exact file privately alongside a consistent SQLite backup.** Possession of both permits credential decryption; encrypt and restrict backups accordingly. To recover, stop the app, restore the matching key file at the same path with mode `0600` and the container user's ownership, restore the database consistently, then restart and test the connections. A missing key with stored credentials fails closed with a recovery instruction instead of generating a replacement. A valid but wrong key cannot decrypt stored credentials; restore the original key or enter replacement provider keys. Removing a connection does not erase older external backups.

The task adds the recoverable key and credential storage, not T17's complete coordinated application backup command or restoration workflow.

## Bounded requests and API boundary

The narrow provider client performs exactly one HTTP request with no retries, redirects, environment proxies, or fallback. Settings allow a 5–60 second total deadline. Response bytes are capped at 64 KiB. General-LLM requests carry a 256–4,096 output-token limit; the Jev contract has no output-token limit parameter, so its probe instead has three fixed questions and a fixed synthetic input. These are request bounds, not a dollar-cost guarantee.

Each provider permits one active probe at a time and at most five reserved attempts per hour across edits and restarts. Reservation precedes network I/O in a SQLite transaction; failures count. A crashed request stays inspectable as pending with unknown usage, ceases to block another attempt after 65 seconds, and still counts against the hourly limit. No attempt is replayed automatically. Known token usage is retained even if output validation fails; missing usage is `null`, never zero. Future run budgets must use these identities/limits and add their own run-level reservation policy.

All routes reuse the existing owner-session and CSRF dependency:

- `GET /api/model-connections` reads sanitized current configuration and last-test status.
- `POST /api/model-connections/{jev|general}/save` accepts validated settings, optional credential replacement, and the expected current revision.
- `POST /api/model-connections/{jev|general}/test` probes the saved revision using synthetic inputs.
- `POST /api/model-connections/{jev|general}/remove` removes the current credential at the expected revision.

Provider response bodies and exception strings never reach the owner. Authentication, timeout, provider quota/rate limit, unsupported request/model, unavailable service, and malformed/incomplete output have distinct application-authored messages. Effective model identifiers are length/character constrained and checked against credential echo. Neither prompts nor provider output bodies are stored in the attempt ledger.

## Verification

Focused Python verification: **21 tests passed**, exercising encrypted-at-rest storage, secret masking, omitted/replaced credentials, independent providers, immutable edit/removal history, restart and key recovery, stale results, persistent request bounds, invalid endpoints/input bounds, authenticated and CSRF-protected mutations, synthetic provider request/response contracts, bounded responses, timeout/auth/429/unsupported-output handling, no redirect/retry, and unknown versus known usage. The only warning is the pre-existing Starlette/httpx TestClient adapter deprecation.

The complete integrated Python regression suite passed **431 tests in 12.47 seconds**, including T03 owner/bootstrap behavior and the concurrent T04 profile/preference implementation.

The integrated Chromium flow passed against the real built Svelte application and temporary FastAPI/SQLite instance. It exercises save, edit with retained key, cleared password fields, reload persistence, independent providers, test-result display, removal confirmation, and 390px mobile overflow. Only the browser's provider-test response is intercepted to avoid sending fake keys externally; the server's actual provider request/validation path is exercised separately using `httpx.MockTransport`. The ignored mobile screenshot was inspected. The combined owner/model/profile browser suite also passed all three tests. Svelte check passed with zero errors/warnings, production build passed, whole-tree Ruff passed, and mypy passed all 37 Python source files.

Reproduce the focused checks from the project root:

```sh
rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q tests/test_model_connections.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m ruff check src/internship_pipeline/model_connections.py src/internship_pipeline/model_connection_router.py src/internship_pipeline/providers tests/test_model_connections.py
rtk proxy /tmp/internship-pipeline-audit-venv/bin/python -m mypy src/internship_pipeline/model_connections.py src/internship_pipeline/model_connection_router.py src/internship_pipeline/providers
```

The space-free virtualenv path is a local verification convenience. In a normal installation, use the project's synced Python environment. From `web/`, run `rtk npm run check`, `rtk npm run build`, and `rtk proxy npx playwright test tests/models.spec.ts`. The browser fixture requires localhost bind permission.

No live provider request was made during the original T05 implementation, no general-LLM key was supplied, and `.env` was left untouched. Its provider evidence above used mocked transport. T02's prior Jev evaluation is separate evidence and was not rerun. No real candidate data, external notifications, commits, or deployment were involved.

## Follow-up — live Jev capability evidence closed

T06's [recorded live client smoke](t06-jev-decisions.md#one-authorized-live-client-capability-smoke), dated October 6, 2026, reports exactly one synthetic request through the actual `ModelConnectionStore.save` → `reserve_test` → `providers.connections.probe` → `complete_test` path against the official TypeSafe endpoint. Selected and resolved model were `jev-1.13.0`; reported usage was **480 input / 102 output tokens**, and persisted readiness was **`ready=true`**. T06 reports an isolated temporary encrypted database, deletion of that database and key afterward, and no changes to real settings. This closes T05's live Jev client capability verification gap. These live facts come from T06's saved handoff; this follow-up did not repeat or independently observe the request, access credentials or `.env`, or mutate real settings.

Direct offline follow-up verification inspected the production router's reservation/probe/completion sequence, the probe's typed output and metadata validation, the store's revision-scoped readiness and ledger, and T06's `assessments.resolved_model` lookup. Three added regression cases exercise the actual store/client chain with `httpx.MockTransport`: a selected alias resolves to a concrete model and survives restart with usage/readiness; invalid evidence output retains known usage but cannot mark the connection ready; and a successful result from an older revision cannot ready a newer saved configuration. The mock usage in these cases is 120/60, separate from the live 480/102 above. No production implementation change was needed.

Focused follow-up checks passed **24 Python tests** and Ruff for the connection store, router, provider client and test file. Commands:

```sh
rtk proxy env PYTHONPATH=src /tmp/t06-test-venv/bin/python -m pytest -q tests/test_model_connections.py
rtk proxy /tmp/t06-test-venv/bin/python -m ruff check src/internship_pipeline/model_connections.py src/internship_pipeline/model_connection_router.py src/internship_pipeline/providers/connections.py tests/test_model_connections.py
```

The live smoke establishes connectivity and typed capabilities only. It does not establish matching quality, production rubric calibration, résumé quality, or automatic-rejection accuracy; the representative human-adjudication and rejection gate remain T21. General-LLM live acceptance remains **T12/T21**, because no credential was supplied. Configurable per-run budgets remain **T08**, and coordinated encryption-key/database backup and full restore remain **T17**. T06's temporary-store success does not deliver those tasks. No additional paid request, evaluation sweep, provider support, notifications, commits, push or deployment occurred in this follow-up.


## October 8 general-provider extension

Both capability probes and résumé selection use `providers/structured.py` for provider-native payloads, authentication and completed-response extraction. The common JSON schema omits array-length keywords unsupported by some providers; local Pydantic validation still enforces one to 100 selected fact IDs, and the existing grounding checks reject invented or repeated IDs. Refusals, truncated responses, missing usage and malformed output cannot mark a connection ready or publish a résumé.

Contracts were checked against the official [Anthropic structured-output guide](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [OpenRouter structured-output guide](https://openrouter.ai/docs/guides/features/structured-outputs), and [OpenAI structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs), alongside Context7's official SDK/documentation sources. No provider SDK dependency was added; the existing bounded HTTPX client remains the transport. Verification evidence is recorded in [T12](t12-tailored-resumes.md).
