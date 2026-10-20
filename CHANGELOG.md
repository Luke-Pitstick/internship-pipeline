# Changelog

## 1.0.2

- Sign-in refreshes the browser session before checking credentials, so password
  recovery and session expiry no longer leave the open form unable to sign in.
  Incorrect credentials show “Incorrect username or password.”
- The Save job button uses the same accent outline as Mark as applied.

Use the [update guide](docs/cli-updates.md) to update an existing installation.
Storage format remains **2**; updates require matching declared storage formats.

## 1.0.1

- Profile settings group experience, projects, and skills into structured sections.
  Location filters use one input with a flexibility checkbox.
- Résumé imports recognize custom LaTeX commands and preserve wrapped bullets,
  education entries, and skill lists when filling the editable profile.
- General model settings load available OpenAI, Anthropic, and OpenRouter models
  without running inference. ChatGPT model selection supports large catalogs and
  shows loading, empty, and error states.
- Source settings group saved searches by provider and offer a source picker.
  A persistent ingestion control stops active collection and scheduled searches;
  restarting queues enabled sources while preserving individual source pauses.
- Jobs can be marked as applied or undone directly from the results list, with
  shared save feedback and updated application status in the detail panel.

Use the [update guide](docs/cli-updates.md) to update an existing installation.
Storage format remains **2**; updates require matching declared storage formats.

## 1.0.0

Internship Pipeline's first stable release brings the self-hosted browser workspace,
guided setup, job review, grounded résumé editing, and explicit host updates together.

- Guided setup saves each step, preserves drafts after errors, and opens Jobs without
  waiting for collection. Models and delivery integrations can be configured later.
- Settings has grouped navigation, independent profile/filter saves and discards,
  integration subviews, and desktop/mobile layouts. Résumé imports fill the existing
  editable profile form.
- The job workspace adds clearer sorting, discovery progress, assessment details,
  protected notes, review actions, and separate application tracking.
- Optional ChatGPT plan connections support account-specific model selection,
  local or remote authorization, usage-limit messages, and disconnect controls.
  API-key provider connections remain available.
- The installer shows download and stage progress. Host commands provide readable
  output, explicit `--json`, password-recovery guidance, and checkout-based development
  commands.
- `internship-pipeline update --check` discovers complete published releases;
  `internship-pipeline update` verifies the selected assets and data copy before
  recoverable cutover. Stable releases supersede their RCs, including promotions
  that reuse the same image bytes.

### Installation and updates

Use the [README](README.md) for installation and the [update guide](docs/cli-updates.md)
for downtime, disk requirements, and recovery. Updates retain the saved engine,
port, owner credentials, and original data volume. A stopped installation remains
stopped; a running installation returns to running. Restored browser sessions are
revoked, so sign in again after updating.

This release declares storage format **2**. Both source and target images must
explicitly declare the same format. Older public previews without that declaration,
and releases with a different format, are refused before downtime. There are no
automatic schema migrations or background updates.

Release acceptance covers synthetic application data and disabled or mocked external
transports. It does not certify a user's paid provider credentials, email destination,
Google Sheets account, or ChatGPT account; test those connections in Settings.
