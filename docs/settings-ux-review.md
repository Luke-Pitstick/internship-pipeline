# Settings flow review — October 19, 2026

Settings now uses a persistent workspace with separate editing and save actions, while onboarding keeps its guided progression. Existing product colors, type, searchable controls and API contracts are retained.

## Findings and changes

- The seven categories previously formed an undifferentiated list that wrapped across several mobile rows. Desktop navigation now groups them under Your search, Workspace and System; mobile uses a labeled section picker. Each section has a short explanation, and unsaved sections have a visible marker.
- Profile and Job Filters previously saved and discarded one shared draft. Each section now saves or discards its own values while preserving the other section's edits. The server still receives the full snapshot with the expected revision, so stale tabs continue to fail safely.
- A selected résumé file was discarded when switching categories, and category changes replaced history entries. The import component now stays mounted in Settings, category/subview links use SvelteKit shallow history, and Back/Forward restores the view without losing drafts. Section changes return to the top of the settings workspace; validation scrolls the focused field into view.
- Import used a large part of the initial Profile screen. It is now expandable in Settings and remains open in guided onboarding. An extracted import must be saved or discarded in Profile before saving filters because its provenance is tied to the profile snapshot revision; the UI explains this and links back to the imported profile.
- Email and Google Sheets appeared in one long panel. They now have separate persistent subviews, independent unsaved markers and shareable hash links.
- Model, email and Sheets forms cleared newly entered secrets before the server accepted a save. They now clear them after success, retain them after failure, and avoid showing secrets in feedback. Model reload clears stale errors and disables editing while loading. Email and Sheets failures use alert feedback; unchanged saved configurations disable Save.
- Source usage limits now use an expandable section, deleting a search asks for confirmation, and a failed initial source load offers Retry. Generation rules use native form validation. Syncing a Sheets preview is disabled while the connection draft has unsaved changes. Diagnostics provides explicit loading, empty and retry states.
- Settings-specific styling improves section spacing, selected states, editable fact groups, control sizes and mobile input text. It is scoped to the settings workspace so it does not impose the desktop settings layout on onboarding.

## Verification

Synthetic browser fixtures exercise real local API persistence without using the owner's data or sending live provider requests. The dedicated settings fixture uses port 4195 and a separate output directory so concurrent agents' browser suites do not delete its setup token or traces.

Verification passed: 19 distinct browser scenarios across the settings, profile, model, import, email, Sheets, source, generation-policy, onboarding, master-PDF and tailored-résumé suites. Svelte check reports zero errors and warnings, the production build succeeds, and scoped whitespace/Ruff checks pass.

Commands are run from `web/`:

- `npm run check`
- `npm run build`
- `npx playwright test --config playwright.settings.config.ts` (settings, profile, model connections and résumé import)
- Dedicated email, Sheets, search, generation-policy, setup, master and tailored Playwright configurations.

Layout checks cover all seven categories at 1440, 768, 390 and 320 CSS pixels. Desktop and mobile screenshots are written under ignored `web/test-results-settings/`; selected screen captures are visually inspected. The test suite checks keyboard focus after category selection, independent saves/discards, stale tabs, history, import preservation, credential-save failures, subview deep links and runtime errors.

This change adds no storage schema, stored-value format or configuration format. It does not establish credentialed provider, real notification, container or deployment acceptance.
