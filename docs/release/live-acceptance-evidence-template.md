# Sanitized live acceptance evidence

Copy this template into the scoped evidence record after the private handoff. Keep secrets and raw transport payloads outside the repository. `pending`, `blocked`, `failed`, `unknown`, `synthetic/native`, and `live/image` are distinct evidence states; fill only observed facts.

## Accepted artifact and authorization

| Field | Value |
| --- | --- |
| Date / UTC window / operator alias | Pending |
| Source SHA / CI URL / tested platform | Pending |
| OCI checksum / local image-config ID / eventual registry digest | Pending; separate identities |
| Seed helper SHA-256 | Pending |
| Final advertised provider/model/interface matrix and concurrent provider handoff | Source contract 8f14e54: OpenAI Responses / Claude Messages / OpenRouter Chat Completions; accepted image and live evidence pending separately |
| Host / runtime / browser versions | Pending |
| Public-source and synthetic-integration resource aliases | Pending |
| Private handoff reference (alias, not a credential path) | Pending |
| Approved total model calls / local reservation cap / account spending control | Pending |
| Approved SMTP deliveries / transport attempts / inbox alias | Pending |
| Approved Sheet runs / row-write requests / cell assignments / OAuth/read limits | Pending |
| Authorized manual Sheet edits / revocation | Pending |
| Stop/reconciliation owner | Pending |

## Scenario observations

| Scenario | Scope/state | IDs/revisions and observation | Evidence reference / UTC time / error |
| --- | --- | --- | --- |
| Public source selection/setup/skip/reload | Pending | Board/source/run identity, real inventory count; model caps zero | Pending |
| Synthetic seed/profile import | Pending | J1/J2 IDs; import/provenance/profile revision; no fake assessments | Pending |
| Jev capability probe | Pending | Connection/selected/effective model; one attempt; usage | Pending |
| OpenAI capability probe | Pending | Connection/selected/effective model; one attempt; usage | Pending |
| Claude / Anthropic probe and grounded generation | Pending | Separate key/model/connection revision and approved envelope; native schema/output/usage contract | Pending |
| OpenRouter probe and grounded generation | Pending | Separate key/model/connection revision and approved envelope; routing constraints and prompt/completion usage | Pending |
| J1/J2 assessments | Pending | Typed outcome, review state, fit/confidence, job/profile/rubric/model revisions | Pending |
| Manual J1 grounded selection/PDF/review/download/logout | Pending | Draft key, selected/omitted facts, readable contact, denial after logout | Pending |
| Automatic J2 draft and disable | Pending | Explicit policy/revision, preview, outcome, manual remains available | Pending |
| SMTP settings test | Pending | Delivery/attempt/config IDs; application acceptance and inbox receipt separately | Pending |
| J1 alert/PDF | Pending | Unique membership, delivery/receipt times, PDF readable | Pending |
| J2 digest | Pending | Distinct membership, configured window and measured receipt | Pending |
| Initial Sheet upsert/readback | Pending | Sheet alias, mapping/config/run, exact two stable IDs, mapped cells | Pending |
| Repeat/inward review/manual/formula preservation | Pending | Same stable IDs, repeated writes, local-before-review state, accept/ignore audit | Pending |
| Revoked Sheet access | Pending | Only disposable account revoked; actionable failure; local work remains | Pending |
| Restart/persistence/no replay | Pending | Same image/data, sessions/settings/documents/ledger, attempt deltas zero | Pending |
| Failure/skip/Applied/stale-revision UI | Pending | Exact harmless inputs and independent worker outcomes | Pending |
| CI recovery reused / S5 restore dependency | Pending | Exact image/report identity and missing operator checks | Pending |

## Attempt ledger

| Provider/surface | Operation and synthetic ID | Ledger/queue attempt | Started/completed UTC | Outcome | Reserved / input / output usage |
| --- | --- | --- | --- | --- | --- |
| Pending | Pending | Pending | Pending | Pending | Unknown until observed |

Count probes separately from run reservations. Include failed, timed-out, rate-limited and interrupted attempts; an unknown usage count doesn't erase the reservation. Distinguish cached drafts from new selection calls. Record SMTP transport acceptance separately from inbox receipt. For Sheets, count repeated row POSTs, readback, token refreshes and operator edits separately; unchanged rows are rewritten by the current sync implementation.

## Sheet preservation snapshot

| Stable job alias / row | A–J before/after match | K/L inward value and review resolution | M manual value preserved | N formula expression/result preserved |
| --- | --- | --- | --- | --- |
| J1 / pending row | Pending | Pending | Pending | Pending |
| J2 / pending row | Pending | Pending | Pending | Pending |

## Final disposition

State which phases passed with actual live/image evidence, which retain synthetic-only evidence, and which are unresolved. Record the remaining external input or source defect and its owner. Include whether all automatic settings are disabled, sources paused, the disposable account remains revoked, owned resource identities are retained, and no resend/replay is authorized. A partial successful path cannot close S2 or the release matrix.
