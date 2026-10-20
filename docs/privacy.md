# Privacy and data flow

This is a private single-owner installation. Local storage, backups and optional destinations contain candidate facts, job/application records and potentially credentials; self-hosting does not prevent data from reaching a provider when you explicitly configure and use it. This document describes the implemented boundaries, not a provider retention promise or a completed security certification.

## What stays local

Owner identity/password hashes and sessions live in `identity.sqlite3`. The jobs database retains observations, confirmed profile/eligibility facts, filter/search/settings/model revisions, matching evidence, overrides, explicit application state and integration/generation ledgers. Documents and associated provenance/artifacts live under the configured private instance paths.

PDF, DOCX and TeX imports parse locally by default in a bounded subprocess. Checking “Use AI to organize résumé fields” enables one request to the saved, tested API connection. A proven PDF-capable connection receives the PDF; other API connections receive locally extracted text, including contact details and links. DOCX and TeX always use local text extraction before optional AI organization. The uploaded binary is discarded after processing; SQLite retains its hash/format, extracted or AI-transcribed source rows and reviewed field-to-source evidence. AI transcriptions are labeled and require review against the original. Master résumés render saved facts locally without a model. Import never executes or compiles uploaded TeX; a reviewed TeX source is retained separately as the tailoring template.

Provider credentials are encrypted at rest using Fernet and the exact instance `model-credentials.key`. Read APIs omit secrets, form fields clear after submission, and provider errors use application-authored messages rather than raw responses. Encryption protects a copied database without its key; a person holding the full private instance or full backup has both. Owner-session, origin and CSRF controls protect browser APIs, while local filesystem/runtime administrators retain access to installation data.

## What leaves the host

| Action | Destination and data |
| --- | --- |
| Collect enabled sources | ATS/JobSpy source services receive network requests and configured search terms/location. Job descriptions and source timestamps return to the local database. |
| Test a model connection | The selected official TypeSafe, OpenAI, Anthropic or OpenRouter endpoint receives an application-owned synthetic candidate/posting or structured fact probe plus the configured authentication credential. The probe does not use your résumé/profile. |
| Import a résumé with AI enabled | The saved, tested API provider receives the PDF if native PDF support is established, or locally extracted text for other models and formats. The request allows up to 8,192 output tokens independently of résumé-generation settings, subject to provider charges and retention policy. OpenAI uses `store: false`; OpenRouter native PDF requests explicitly disable intermediary OCR, and text requests disable optional reasoning only when the exact model advertises support. Catalog checks may occur. ChatGPT account connections use local parsing. Failed, invalid or detected incomplete model output is discarded and local extraction is used with an explicit notice. Text-mode output is checked against the extracted source; native PDF transcriptions require visual review. |
| Match a job | TypeSafe receives supported candidate skills/experience/eligibility facts, preferences and untrusted job context needed for criterion/evidence/fit decisions. |
| Generate a tailored résumé | The selected OpenAI, Claude (Anthropic) or OpenRouter provider receives confirmed selectable facts and job context. OpenAI requests set `store: false`; each provider has its own retention rules. Switching providers requires a key for the new provider and a new capability test. Master generation and local import need no model. |
| Test/send email | The configured SMTP server receives sender/recipient, the synthetic test or selected job alert/digest, and optional available PDF attachments when requested. Message recipients receive that content. |
| Test/sync Sheets | Google OAuth/Sheets receives service-account authorization and spreadsheet identifiers; queued sync sends explicitly mapped job facts. Selected inward status/notes are read into owner-review proposals. Unmapped columns remain unowned by the application. |

Saving model, SMTP or Sheets settings does not initiate those provider actions. Test buttons perform external checks when using live credentials; queued work and explicitly enabled schedules/automatic policies can make later calls without another click. Email and Sheets are independently optional. General-LLM/model output may be malformed or incomplete, and supporting evidence/validation remains required before a draft is presented as reviewed.

## Retention, disconnect and recovery

Disconnecting a connection removes its active encrypted credential and disables dependent future work. Immutable local revision/attempt audit metadata, earlier documents, backups and data already delivered externally may remain. Disconnect is not an erasure request to a provider or message recipient. There is no general-purpose account/data-erasure UI contract in this release preparation; set a retention policy for your own volume, backups and optional destinations.

Full backup contains the identity/jobs databases, encryption key, configuration, provenance and document bytes, with manifest verification. Stop all supported writers first, restrict backup access to the owner and protect any off-host copy. Restore into a fresh instance retains confirmed delivery/sync work, revokes sessions and leaves interrupted side effects for explicit review. Loss of the exact key prevents decrypting saved credentials; a new key cannot recover them. See [backup and recovery](support.md#full-backup-and-fresh-restore).

Source timestamps, first observation and notification timestamps are distinct. Marking Applied records an owner action; the app does not submit an application or send résumés to employers. Reviewed inward Sheets status changes also require an explicit owner acceptance.

## Sharing diagnostics

Authenticated Diagnostics presents bounded counts, source freshness, worker state and sanitized errors. Raw container/application logs can include the first-run private owner setup URL; database files, manifests, document artifacts and full backups can include personal data or secrets. Share a sanitized issue description and synthetic reproduction, not a volume, backup, `.env`, résumé, setup token, service-account JSON, password or session cookie. [Support](support.md) lists safe context and the remaining private security-contact release requirement.

The repo ignores private/local runtime paths and restricts its image build context. Those controls do not remove a previously tracked file or guarantee every new output path is ignored. [Contributing](../CONTRIBUTING.md) requires synthetic committed fixtures and staged-diff review. Review source and packaged artifacts for private data before publication.
