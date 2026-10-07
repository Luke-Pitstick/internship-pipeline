# Contributing

This repository is preparing a release, and the project license is not yet selected. Review [redistribution readiness](docs/redistribution-review.md) before relying on a redistribution grant. Changes should keep the smallest complete workflow working and record which acceptance boundary they actually verify.

## Development setup

Use Python 3.12+, uv and Node.js 22. Install the locked dependencies with `uv sync --frozen --python 3.12` at the root and `npm ci` in `web/`. Build the frontend before starting the native application or browser suites. PDF checks require a working `pdflatex` installation with the packages used by `src/internship_pipeline/resumes/master_template.py`; application builds use TeX from the Dockerfile.

Follow [AGENTS.md](AGENTS.md) and the ordered [implementation plan](docs/implementation-plan.md). Python modules live in `src/internship_pipeline`, frontend routes/components in `web/src`, synthetic tests in `tests` and `web/tests`, operator tooling in `deploy`, and task contracts/evidence in `docs`. [Architecture](docs/architecture.md) explains the current seams.

## Checks

Run from the repository root:

```sh
uv run --frozen ruff check src tests deploy
uv run --frozen mypy --strict src/internship_pipeline
uv run --frozen pytest -q
uv build
git diff --check
```

Run frontend checks from `web/`:

```sh
npm run check
npm run build
npm run measure
npx playwright test --config playwright.config.ts
npx playwright test --config playwright.setup.config.ts
```

The default browser suite excludes the fresh setup test, so both commands matter. Feature suites have dedicated configurations for search, jobs, generation policy, master/tailored résumés, email and Sheets; run the configuration appropriate to the changed behavior. Browser fixtures start local listeners and use temporary synthetic instances. Install Playwright Chromium separately if it is unavailable in the development environment; CI does that before browser checks.

For direct tests in an existing virtualenv, use `PYTHONPATH=src .venv/bin/python -m pytest`. Some temporary-executable tests are sensitive to a virtualenv path containing spaces; use a space-free virtualenv when reproducing that environment problem. Give concurrent pytest runs distinct unused `--basetemp` paths to avoid shared temporary-output interference. [Integrated acceptance](docs/integrated-acceptance.md) records the current reproducible baseline rather than certifying every future edit.

## Data and provider boundaries

Commit synthetic candidate facts, source postings, résumé fixtures and service responses only. `.env`, private documents, credentials, local YAML, databases, generated artifacts and browser outputs belong in ignored paths; check the actual staged diff because ignoring a path does not remove an already-tracked file. Do not place credentials in URLs, screenshots, issue text or command arguments.

Use synthetic transports and isolated storage for ordinary tests. A connection probe can charge a model account; SMTP tests send messages; Sheets tests can change remote cells. Live acceptance requires owner-supplied credentials, a bounded authorized action and a disposable destination where appropriate. Passing mock/native tests must remain labeled mock/native, and no optional integration may become a collection prerequisite.

Keep source publication time, first observation and notification time separate. Treat job text as untrusted matching input, persist supported evidence and uncertainty, and route model-derived rejection to review while the quality gate is unmet. Generate documents only from confirmed facts; imported files are data, never executable templates. Applied records require an explicit owner action.

## Changes and handoffs

Own a bounded concern, preserve concurrent edits and remove obsolete paths instead of adding fallback compatibility. Add meaningful tests at the behavior boundary when the change warrants them, run relevant checks, then record exact commands, source revision/scope and limitations in the task handoff. Report newly exposed defects instead of relabeling a failing check as an environment pass.

For container changes, use the [T18 isolated smoke/recovery runner](docs/t18-portable-images.md) only on an authorized healthy runtime. Its real-engine checks create and clean uniquely owned test resources; they are a separate boundary from native tests. Do not reset/prune an operator's runtime or remove a persistent installation to make acceptance pass. Image publication, supported platform claims and a hosted installer remain release gates in [release readiness](docs/release-readiness.md).

## Reporting issues

Include the source/image version, host OS/architecture, runtime, affected workflow, sanitized status/error code and a synthetic reproduction. [Support](docs/support.md) explains which diagnostics are safe to share. The repository has no published private security-reporting contact yet; establishing that contact is a release requirement. Keep exploitable security details and personal installation data out of public reports until an appropriate private reporting route exists.
