# Internship Pipeline

A self-hosted internship workspace: collect jobs, assess fit against confirmed candidate facts, review résumé drafts, and optionally receive email or sync a Google Sheet. You submit applications yourself and record Applied explicitly.

This checkout is **release preparation**. The latest [downstream verification](docs/release/completion-status.md) passes 866 Python tests, six default browser tests, one fresh guided-setup test and one 10,000-job workspace test using synthetic provider transports. No container image is published, no OS/architecture/runtime support matrix is certified, and live general-LLM, SMTP and Google Sheets acceptance remain open. Model-derived rejections go to review because the independent quality gate is unmet. See the [release acceptance matrix](docs/release-readiness.md) before choosing a deployment path.

## Start from source

The intended deployment is one container containing the web app, Python workers and PDF renderer, with one persistent data volume. The repository's Compose path is available for testing on a healthy Docker engine, but its actual build/lifecycle/recovery checks have not passed yet:

```sh
docker compose up --build -d
docker compose logs app
```

Read the one-time owner setup token privately from the log, then open [localhost:8080](http://localhost:8080). The log is sensitive until the owner is claimed. Set `PIPELINE_PORT` when choosing a different local port; Compose derives the corresponding browser origin. `docker compose stop` preserves the data volume. Follow [deployment](docs/deployment.md), [operations](docs/t17-operations.md) and [support](docs/support.md) for exact persistence and recovery constraints.

For optional Compose overrides, copy [.env.example](.env.example) to the ignored `.env` file. Its values are blank and use Compose's local defaults. Enter model API keys, SMTP credentials and Google Sheets access in the app's Settings; Compose does not read those credentials from `.env`.

There is no hosted one-command installer or published image URL yet. [Local explicit-image installer preparation](docs/t19-installer.md) requires Python 3.12+ and the complete reviewed deploy bundle; `sh deploy/install.sh --help` is a safe way to inspect it. [Management preparation](docs/t20-management.md) supplies lifecycle commands and authenticated diagnostics against its [saved manifest](docs/installation-manifest.md). A versioned image, healthy runtime and real acceptance evidence are prerequisites for recommending that path.

For a native development installation, use Python 3.12+, uv and Node.js 22. Install a local `pdflatex` environment with the template's packages if testing PDFs; the proposed image provides TeX itself. From the repository root:

```sh
uv sync --frozen --python 3.12
cd web
npm ci
npm run build
cd ..
PIPELINE_DATA_DIR="$PWD/private/dev-instance" \
PIPELINE_WEB_DIR="$PWD/web/build" \
PIPELINE_ORIGIN=http://localhost:8080 \
uv run --frozen python -m internship_pipeline.bootstrap
```

The final command creates an ignored local installation, prints its setup token and supervises the application. Keep that terminal running and visit the same local URL. A new instance starts without configured models or sources; later saved connections and enabled searches can make external requests, so use synthetic fixtures for development acceptance.

## Finish setup in the browser

1. **Claim the owner account.** Enter the one-time token and choose the username/password. Setup resumes from its saved checkpoint after reload; an already-owned installation requires sign-in.
2. **Configure AI Models.** Jev uses TypeSafe's official endpoint; the independent résumé LLM supports OpenAI, Claude (Anthropic), and OpenRouter. Select its provider, enter a model and API key, then save and test. Saving credentials makes no provider call. Testing submits a bounded synthetic request and may incur provider charges. You can defer a missing model and return to Settings later.
3. **Confirm your profile and filters.** Enter supported facts or import a PDF/DOCX and review extracted fields before saving. Import is local and makes no model call. Keep mandatory eligibility requirements distinct from soft preferences; uncertain evidence stays inspectable.
4. **Save a search and choose integrations.** Configure sources in Settings, then review the saved search. Email and Sheets can each be connected or skipped independently. CSV export needs no Google credential. Review the final setup preview before starting the first search.
5. **Review useful results.** Inspect source posting date separately from first observation, persisted fit/evidence and run status. Initial board inventory is labeled backlog. Generate a master PDF from saved facts or request a tailored draft after the general LLM is ready, review its changes, and mark Applied only after submitting the application yourself.

[Guided setup](docs/t16-guided-setup.md) records the fresh native journey and the remaining container/live boundary. [Search controls](docs/t08-saved-searches.md), [jobs](docs/t09-jobs-workspace.md), [résumé import](docs/t10-resume-import.md), [master rendering](docs/t11-master-resume.md) and [tailoring](docs/t12-tailored-resumes.md) describe the implemented workflows. Automatic résumé generation is off by default and requires an explicit bounded policy under [Resume Generation](docs/t13-generation-policy.md).

## Providers and operating limits

| Capability | Implemented contract | Acceptance boundary |
| --- | --- | --- |
| Job sources | Ashby, Greenhouse and Lever direct boards; configured JobSpy searches | Complete board snapshots alone can close jobs after two complete misses; aggregators cannot reopen directly closed jobs. Real source availability and throttling vary. |
| Jev matching | Official TypeSafe SystemOne endpoint, typed criterion/evidence/score output | One historical synthetic live capability probe passed; representative quality and automatic rejection remain unvalidated. |
| General LLM | OpenAI Responses, Anthropic Messages, or OpenRouter Chat Completions; structured JSON output and usage metadata | Synthetic transport and real local PDF validation pass for all three providers; credentialed live acceptance remains open. Use a model supporting structured outputs. |
| Email | SMTP STARTTLS or implicit TLS through Apprise; alerts or daily digest | Synthetic transport acceptance passes; actual mailbox receipt and attachment delivery are open. Ambiguous acceptance requires owner review. |
| Google Sheets | Dedicated service account, explicit columns, preview, stable-ID write/readback and reviewed inward changes | Synthetic HTTP/auth/worker checks pass; live disposable-sheet acceptance is open. Google offers no conditional per-cell write, so concurrent edits inside the write interval remain a limit. |

Configure providers in authenticated Settings. See [model connections](docs/t05-model-configuration.md), [SMTP](docs/t14-email-alerts.md), [Sheets authorization/mapping](docs/t15-spreadsheet-sync.md) and [privacy/data flow](docs/privacy.md) before supplying credentials. Backoff and provider outages can extend polling and delivery intervals; current timings are not a publication-to-alert guarantee. Broad daily discovery is optional and its directory entries need source validation.

## Architecture, contribution and release evidence

The static SvelteKit frontend and FastAPI API share one origin. SQLite holds job observations, immutable settings/model/profile revisions, durable tasks and delivery/sync ledgers; an independent SQLite database holds owner identity. A supervisor runs collection, matching, generation, saved searches, email, Sheets and discovery in separate processes so a slow provider cannot block collection. The application never submits applications. See [architecture](docs/architecture.md) for module boundaries and [contributing](CONTRIBUTING.md) for reproducible synthetic checks.

Full backup includes both databases, the exact credential-encryption key, config, provenance and documents. Stop every supported writer before backup and restore only into a fresh installation; a database-only copy is insufficient. [Operations](docs/t17-operations.md) covers restore validation, session revocation, uncertain side effects and local owner recovery. [Support](docs/support.md) covers diagnostics and safe failure handling.

The project now carries the [MIT license](LICENSE) and matching package metadata. [Redistribution review](docs/redistribution-review.md) tracks the remaining third-party/image notice and asset-provenance work, and [SECURITY.md](SECURITY.md) records the private-reporting setup still required before public release. Historical audits remain evidence of earlier snapshots; [integrated acceptance](docs/integrated-acceptance.md), [portable-image gates](docs/t18-portable-images.md) and [release readiness](docs/release-readiness.md) govern current claims.
