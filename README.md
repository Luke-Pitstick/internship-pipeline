<h1 align="center">Internship Pipeline</h1>

<p align="center">
  <strong>A self-hosted workspace for finding internships and preparing grounded applications.</strong><br />
  Collect jobs, understand your fit, review résumé drafts, and track what you apply to.
</p>

<p align="center">
  <img alt="Project status: release preparation" src="https://img.shields.io/badge/status-release%20preparation-f59e0b" />
  <img alt="Python 3.12 or newer" src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&amp;logoColor=white" />
  <img alt="SvelteKit frontend" src="https://img.shields.io/badge/frontend-SvelteKit-FF3E00?logo=svelte&amp;logoColor=white" />
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-6f42c1" /></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#development">Development</a> ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

Internship Pipeline brings job discovery, eligibility review, résumé preparation and application
tracking into one private workspace. Run it on your own machine, connect the sources and providers
you choose, and keep the final decisions in your hands. You submit applications yourself.

## Why Internship Pipeline

Finding a posting is only the first step. You still need to check its requirements, decide whether
it fits, prepare a résumé and remember what happened next:

- **Search once, keep collecting** — save searches across Ashby, Greenhouse, Lever and configured
  JobSpy sources, with posting dates and first-observed timestamps kept separately.
- **Inspect the reasoning** — review Jev's eligibility evidence, fit, confidence and uncertain
  criteria alongside the original posting. Model-derived rejections go to review.
- **Prepare résumés from your facts** — import and confirm your experience, then generate a master
  PDF or request a tailored draft using OpenAI, Claude or OpenRouter.
- **Keep applications organized** — save jobs, add notes, inspect assessments and mark Applied
  explicitly after submitting an application.
- **Connect only what you need** — enable SMTP alerts or digests and Google Sheets sync separately,
  or work in the browser and export CSV.

## Project status

This repository is in **release preparation**. The latest [native verification](docs/release/completion-status.md)
passed 866 Python tests and eight browser cases, including fresh setup and a 10,000-job workspace.
Those checks use synthetic provider transports.

> [!IMPORTANT]
> There is no published container image or hosted installer yet. The final combined candidate
> still needs image acceptance, and no OS/architecture/runtime support matrix is certified.
> Live general-LLM, SMTP and Google Sheets acceptance remain open.
> See the [release acceptance matrix](docs/release-readiness.md) before choosing a deployment path.

Automatic model-derived rejection remains disabled behind an independent quality gate. Review
routing is the current behavior; a successful connection test does not establish matching accuracy.

## Requirements

For the source-based container setup:

- Git and a working Docker engine with Docker Compose.
- Network access to build the image and query any sources or providers you enable.
- Persistent local storage for accounts, jobs, settings and documents.
- A browser to claim the owner account and finish setup.

You can claim the account and explore setup without model credentials. Matching requires a Jev
connection; tailored résumés require a separate supported general-LLM connection. SMTP and Google
Sheets are optional. No numerical memory or disk minimum is certified yet.

Native development additionally requires Python 3.12+, uv, Node.js 22 and a working `pdflatex`
environment with the template's packages when testing PDF generation.

## Quick start

The current container path builds from source. It is available for testing while final release
acceptance is being completed:

```bash
git clone https://github.com/Luke-Pitstick/internship-pipeline.git
cd internship-pipeline

# Optional: copy the blank template if you want local port/origin overrides.
cp .env.example .env

docker compose up --build -d
docker compose logs app
```

Read the **Owner setup token** privately from the startup log, open
[http://localhost:8080](http://localhost:8080), and claim the owner account. Keep the log private:
the first-boot token authorizes account creation.

Then complete the guided setup:

1. **Confirm your profile.** Enter your experience or import a text-bearing PDF/DOCX, review the
   extracted facts and save the information you're comfortable using in applications.
2. **Set your filters and models.** Choose your constraints and preferences, connect Jev for
   matching, and select a general provider/model for tailored drafts. Missing connections can be
   deferred. Saving a key makes no request; testing it may incur provider charges.
3. **Choose sources and integrations.** Create a saved search, configure its sources, and optionally
   connect email or Sheets. Review the setup preview before starting the first search.
4. **Review your results.** Inspect the source, assessment and résumé draft, then record Applied
   only after submitting the application yourself.

Setup progress persists across reloads. The initial board inventory is labeled backlog, and
collection can continue independently of model or notification readiness.

The [deployment guide](docs/deployment.md) covers origins, owner claim and persistence. The
[prepared standalone installer](docs/t19-installer.md) requires a complete reviewed bundle and an
explicit image; it is not yet a published one-command installation.

## Configuration

Use authenticated **Settings** for candidate information, models, sources and integrations.
Credentials are not read from `.env` by the Compose service.

| Setting | Where to configure it | Purpose |
| --- | --- | --- |
| Profile and job filters | Browser Settings | Confirmed candidate facts, eligibility constraints and preferences |
| Jev | AI Models | TypeSafe matching connection and its tested revision |
| General LLM | AI Models | OpenAI Responses, Claude/Anthropic Messages or OpenRouter Chat Completions |
| Sources and saved searches | Browser workspace | Where to collect jobs, search criteria, schedules and run budgets |
| Résumé generation | Resume Generation | Explicit automatic-generation opt-in and policy; off by default |
| Email | Notifications & Integrations | SMTP STARTTLS or implicit TLS, recipient, alerts/digest and optional PDFs |
| Google Sheets | Notifications & Integrations | Dedicated service account, shared spreadsheet, tab and column mapping |
| `PIPELINE_PORT` | Local `.env` | Host port; blank defaults to `8080` |
| `PIPELINE_ORIGIN` | Local `.env` | Browser origin; blank derives `http://localhost:<port>` |

[.env.example](.env.example) intentionally contains only blank values. Keep your actual `.env`
ignored, and never commit API keys, service-account files, private profiles or generated documents.
For remote access, configure an HTTPS reverse proxy and the exact public origin while keeping the
upstream port private; follow the [deployment guide](docs/deployment.md).

Google Sheets uses a dedicated service account with Editor access to the selected spreadsheet.
Preview mappings before syncing. Manual notes and formulas should remain outside application-owned
columns; mapped inward status/notes changes require review. See [Sheets setup](docs/t15-spreadsheet-sync.md).

## How it works

The application runs a static SvelteKit frontend and FastAPI API on one origin. One container
contains the app, Python workers and PDF renderer, with one persistent data volume:

```text
Job sources → Stored postings → Jev assessment → Your review
                                      │
Confirmed profile + selected job → Tailored draft → Reviewed PDF
                                      │
                         Optional email / Google Sheets
```

Collection, matching, résumé generation, email and Sheets run independently. A slow model or
failed delivery does not prevent collection. SQLite stores observations, revisioned settings,
durable tasks and delivery history; a separate SQLite database holds owner identity.

Résumé generation uses confirmed candidate facts and treats job descriptions as untrusted input.
The application records your decisions but never submits an application. See
[architecture](docs/architecture.md) and [privacy/data flow](docs/privacy.md) for the module and
provider boundaries.

## Everyday commands

For the Compose installation above, run these from the checkout:

| Command | Purpose |
| --- | --- |
| `docker compose ps` | Inspect the application container and health state |
| `docker compose logs --tail 100 app` | Read recent startup/worker logs privately |
| `docker compose stop` | Stop the application while retaining its data volume |
| `docker compose start` | Start the existing stopped application |
| `docker compose restart app` | Restart the application while retaining its data volume |

The prepared host installer has a separate [management command](docs/t20-management.md) for its
saved installation. Its runtime wrapper and the in-container Python maintenance CLI have distinct
purposes despite sharing the `internship-pipeline` name.

## Data and recovery

The persistent volume contains jobs, settings, owner identity, encrypted credentials and documents.
A complete backup must include both databases, the exact credential-encryption key, configuration,
provenance and artifact bytes. A copy of the jobs database alone is not enough.

Stop the application and all separately launched workers before backing up. Restore into fresh
storage using the exact source image, verify sign-in and documents, and retain the original until
the restored installation is verified. Current recovery does not provide cross-version upgrades.
Follow the [backup and recovery instructions](docs/t20-management.md#private-backup-and-recovery)
and [operations guide](docs/t17-operations.md).

## Development

From a checkout, install the locked dependencies and build the frontend:

```bash
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

Keep that terminal running and open the local URL. The command creates an ignored local
installation, prints its owner setup token and supervises the app and ready workers.
Use synthetic profiles and provider transports for development.

Run the core checks from the repository root:

```bash
uv run --frozen ruff check src tests deploy
uv run --frozen mypy --strict src/internship_pipeline
uv run --frozen pytest -q
```

Frontend checks run from `web/`:

```bash
npm run check
npm run build
npm run measure
npx playwright test --config playwright.config.ts
npx playwright test --config playwright.setup.config.ts
```

Install Playwright Chromium if it is unavailable. PDF tests require the local TeX environment.
[CONTRIBUTING.md](CONTRIBUTING.md) covers feature-specific browser suites, isolated test data and
checks needed for a change.

## Troubleshooting

### The browser cannot connect

Confirm Docker is running, inspect `docker compose ps`, and check the configured port and origin.
Open the exact configured origin. Preserve the existing volume while diagnosing startup problems.

### The setup token is rejected

The token is single-use. If the installation is already claimed, sign in with the owner account.
For a lost password, use the stopped-installation [owner recovery procedure](docs/deployment.md#account-recovery).

### No jobs or résumé drafts appear

Check enabled sources, the saved search and its latest run in the browser. Matching needs a tested
current Jev connection; tailored drafts need a confirmed profile and tested general-LLM connection.
Profile or model changes can make an older assessment or draft stale. Inspect Settings → Diagnostics
before retrying work.

### Email is uncertain or Sheets sync stops

SMTP acceptance does not prove mailbox receipt. Check the delivery history and inbox before
retrying an uncertain send. For Sheets, inspect sharing permissions, mapping and changed-cell
conflicts, then prepare a fresh preview. See [email](docs/t14-email-alerts.md),
[Sheets](docs/t15-spreadsheet-sync.md) and [support](docs/support.md).

## Contributing

Focused fixes and synthetic reproductions are welcome. Include the source/image version, host,
runtime, affected workflow and sanitized error code in a report. Keep setup tokens, credentials,
private candidate facts and raw provider responses out of public issues.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions and [SECURITY.md](SECURITY.md)
for the private-reporting policy and its outstanding setup requirement.

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses and notices; the
[redistribution review](docs/redistribution-review.md) tracks the remaining image and asset review.
