# Changelog

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
