<h1 align="center">Internship Pipeline</h1>

<p align="center">
  <strong>A self-hosted workspace for finding internships and preparing grounded applications.</strong><br />
  Collect jobs, understand your fit, review résumé drafts, and track what you apply to.
</p>

## Install with one command

```sh
curl -fsSL https://raw.githubusercontent.com/Luke-Pitstick/internship-pipeline/main/install.sh | sh
```

You'll need **Python 3.12+, curl, and Docker or Podman**. The installer starts the app and opens
account setup with just username and password. See [requirements](#requirements) and
[first-time setup](#quick-start).

<p align="center">
  <img alt="Version: 1.0.0" src="https://img.shields.io/badge/version-1.0.0-3776AB" />
  <img alt="Python 3.12 or newer" src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&amp;logoColor=white" />
  <img alt="SvelteKit frontend" src="https://img.shields.io/badge/frontend-SvelteKit-FF3E00?logo=svelte&amp;logoColor=white" />
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-6f42c1" /></a>
</p>

<p align="center">
  <a href="#installation">Install</a> ·
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

Current version: **1.0.0**. See the [release notes](CHANGELOG.md) for changes and update instructions.

## Installation

Use the [curl command above](#install-with-one-command), then finish setup in your browser.
The installer starts the application and opens account setup where you choose a username and
password. If the browser doesn't open, use the link printed in your terminal.

Start Docker or Podman before installing. On macOS, the installer can open an installed Docker
Desktop for you. For source setup, see [Development](#development).

## Requirements

- **macOS or Linux**, on an Intel/AMD 64-bit or ARM64 machine.
- **Python 3.12+** and **curl**.
- **Docker Desktop, Docker Engine, or Podman** to run the app.
- A browser, an internet connection, and local storage for your data.

Matching requires a **Jev** connection; résumé drafts use **OpenAI, Claude, or OpenRouter**.
You can set up your account before connecting providers. Email and Google Sheets are optional.

## Quick start

1. **Add your profile.** Import a PDF or DOCX résumé, or enter your experience manually.
2. **Choose your preferences.** Set the roles, locations, and requirements that matter to you.
3. **Connect your models.** Set up matching and résumé generation in the browser.
4. **Finish setup and review jobs.** Collection starts automatically. Review matches,
   prepare drafts, and mark jobs as applied after you submit them.

You can change your profile, sources, models, and integrations in Settings.

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
columns; mapped inward status/notes changes require review. See [Sheets setup](docs/deployment.md#optional-email-and-google-sheets).

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

The hosted installer places a management command in `~/.local/bin` by default. Add that directory
to your `PATH`, or use the absolute command path printed by installation:

```bash
internship-pipeline open
internship-pipeline status
internship-pipeline url
internship-pipeline stop
internship-pipeline start
internship-pipeline update --check
internship-pipeline update
```

These commands use the saved runtime and installation; they do not require a source checkout.
Use `update --check` to check for a compatible release and `update` to install it.
Rerunning the installer keeps the existing version. See the [update guide](docs/cli-updates.md)
for older installations, and the [management guide](docs/support.md#diagnose-a-running-installation) for diagnostics.

For a source-based Compose installation, run these from its checkout:

| Command | Purpose |
| --- | --- |
| `docker compose ps` | Inspect the application container and health state |
| `docker compose logs --tail 100 app` | Read recent startup/worker logs privately |
| `docker compose stop` | Stop the application while retaining its data volume |
| `docker compose start` | Start the existing stopped application |
| `docker compose restart app` | Restart the application while retaining its data volume |

The host management command and the in-container Python maintenance CLI have distinct purposes
despite sharing the `internship-pipeline` name. Use the command for your installation type.

## Data and recovery

Your jobs, settings, credentials, and documents are kept in persistent storage. Follow the
[backup and recovery guide](docs/support.md#full-backup-and-fresh-restore) to make a complete
backup or restore an installation.

## Development

Source-based development requires Git. To build and run the container locally:

```bash
git clone https://github.com/Luke-Pitstick/internship-pipeline.git
cd internship-pipeline
# Optional local Compose overrides; keep the real .env ignored.
cp .env.example .env
docker compose up --build -d
docker compose logs app
```

Native development additionally requires Python 3.12+, uv, Node.js 22 and a working `pdflatex`
environment with the template's packages for PDF generation. From a checkout, install the locked
dependencies and build the frontend:

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
installation, prints its private **Owner setup URL** and supervises the app and ready workers. Open that full
link to choose your username and password.
For API auto-reload, add `--reload` to the bootstrap command. This binds the API to loopback
and keeps the worker supervisor running while source edits reload the API. Collection workers
start automatically when onboarding is complete; integration workers can run during setup to
process connection tests. Use this supervised launcher for previews so queued searches are consumed.
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

### Docker or Podman is installed, but no healthy engine is found

The installer needs a responding Linux engine, not only an installed CLI. On macOS, open
Docker Desktop and wait for `docker info` to succeed before rerunning the installer:

```sh
open -a Docker
docker info
```

For Podman on macOS, inspect `podman machine list` and start your existing machine with
`podman machine start`. If the list is empty, initialize a machine with `podman machine init`
before starting it. Confirm `podman info` succeeds. The installer preserves your selected
connection and does not create Podman machines. If both engines are healthy, select one explicitly:

```sh
curl -fsSL https://raw.githubusercontent.com/Luke-Pitstick/internship-pipeline/main/install.sh | sh -s -- --runtime docker
```

### The browser cannot connect

For a hosted installation, inspect `internship-pipeline status` and `internship-pipeline url`.
For source Compose, inspect `docker compose ps`. Confirm the selected runtime is running and open
the configured origin. Preserve the existing volume while diagnosing startup problems.

### The setup link is missing or expired

Run `internship-pipeline open` on the host to open a fresh private setup link. Old setup links
are single-use and are invalidated when a new one is issued. If the installation is already
claimed, the command opens ordinary owner sign-in.
For a lost password, see [Forgot your password?](#forgot-your-password) below.

### No jobs or résumé drafts appear

Check enabled sources, the saved search and its latest run in the browser. Matching needs a tested
current Jev connection; tailored drafts need a confirmed profile and tested general-LLM connection.
Profile or model changes can make an older assessment or draft stale. Inspect Settings → Diagnostics
before retrying work.

### Email is uncertain or Sheets sync stops

SMTP acceptance does not prove mailbox receipt. Check the delivery history and inbox before
retrying an uncertain send. For Sheets, inspect sharing permissions, mapping and changed-cell
conflicts, then prepare a fresh preview. See [integration setup](docs/deployment.md#optional-email-and-google-sheets) and
[troubleshooting](docs/support.md#common-failures).

## Forgot your password?

On the computer where you installed the app, open a terminal and run
`internship-pipeline stop`, then `internship-pipeline recover-owner`. Enter the
username you want to use and a new password when prompted. After the reset succeeds,
run `internship-pipeline start` and `internship-pipeline open`, then sign in with
those details. Your saved work stays in place.

If someone else installed the app, ask them to reset it for you.
See the [password reset guide](docs/password-recovery.md) for the full steps,
troubleshooting, and Docker Compose instructions.

## Contributing

Focused fixes and synthetic reproductions are welcome. Include the source/image version, host,
runtime, affected workflow and sanitized error code in a report. Keep setup tokens, credentials,
private candidate facts and raw provider responses out of public issues.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions and [SECURITY.md](SECURITY.md)
for the private-reporting policy.

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses and notices.
