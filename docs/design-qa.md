# Flat dashboard design QA — October 6, 2026

final result: passed

This is a visual refinement of the existing Svelte dashboard, not a new implementation-plan capability. Three independent built-in ImageGen explorations grounded in the running app informed the change. The implementation uses the first Jobs concept and the third Settings concept while retaining the supported product data and workflows.

## Visual sources and captures

- Sources: `web/design/flat-jobs-reference.png` and `web/design/flat-settings-reference.png` (1487 × 1058 pixels).
- Desktop implementation: `artifacts/flat-design/jobs-populated-desktop.jpg` and `artifacts/flat-design/settings-desktop.jpg` (1440 × 1024 pixels, matching CSS viewport and 1× density).
- Full comparisons: `artifacts/flat-design/jobs-comparison.jpg` and `artifacts/flat-design/settings-comparison.jpg`. Source images were scaled proportionally into a 1440 × 1024 slot; implementation captures were not rescaled. Both artifacts were inspected together.
- Mobile: `artifacts/flat-design/jobs-mobile.jpg`, `settings-mobile.jpg`, `jobs-populated-mobile-list.jpg`, and `jobs-populated-mobile-detail.jpg` at 390 × 844 CSS pixels.
- Focus comparison: `artifacts/flat-design/search-focus-comparison.jpg`. User-supplied bug screenshot and browser-rendered fixed control were inspected together; the final crop is `search-focus-fixed.jpg`.

States: authenticated Jobs with three synthetic opportunities and Northstar Labs selected; authenticated Settings with an empty profile; fresh empty Jobs; focused search on desktop and mobile. The populated state ran at localhost:8090 using a temporary database and a synthetic account, then was stopped. The user's development database was not seeded or changed.

## Findings and corrections

- The reported search focus bug came from the global focus-visible outline on the nested search input. The search-field wrapper now owns the focus-within outline, including the icon; the inner input has no competing outline. Computed styles and desktop/mobile captures confirm a single full-control focus ring.
- Initial flat rendering still reserved space for company initials above the detail heading. Removed those redundant initials and aligned the heading and plain eligibility status, bringing the content up without changing selection or keyboard focus behavior.
- Pending eligibility now uses muted text rather than the positive eligibility color. Confirmed Eligible and Needs review retain distinct text colors.
- An initial Settings comparison used a different viewport. It was replaced by a 1440 × 1024 capture and compared again at the matching aspect ratio.
- Final review found no actionable P0/P1/P2 visual or interaction issues in the scoped screens.

## Fidelity surfaces

- Typography: retained the existing Inter/system sans stack, navy headings, and readable muted body text. Field labels and detail copy use 14px; secondary metadata stays compact.
- Layout: continuous white canvas, thin rules, flat job rows, one list/detail separator, unboxed settings and fact/import sections. Active tabs use underlines or a leading rule. Inputs and buttons retain 3px corners for their affordance. Empty jobs omit the unused detail panel and pagination.
- Color: existing indigo accent remains on primary actions, selection rules, and focus. No section shadows, enclosing rounded cards, or colored status pills remain in the scoped UI.
- Assets: no raster images are shipped as UI. The existing IP wordmark is retained; generated PNGs are design references only. Redundant company initial avatars were removed.
- Content: the mock's invented fields, stale dates, Apply now CTA, fabricated scores, and synthetic profile defaults were not added. Posted, First observed, and application submission stay distinct. Profile forms keep their evidence-based fact workflow instead of the mock's unsupported free-form summary fields. The retained application data contract accounts for differences in form density and detail facts.

## Verification

- Svelte check: zero errors and warnings after final changes.
- Static build and git diff --check: passed.
- Existing dashboard, model settings, profile/filter, and résumé-import browser scenarios: four passed.
- The separate master résumé scenario was not validated: the general suite lacked its setup fixture, and its dedicated configuration subsequently timed out during account setup. These failures occurred before the redesigned résumé controls were exercised; they are not counted as passes.
- Manual in-app browser: mark applied, Applied filtering, Undo, mobile selection, Escape return with focus restoration, and Jobs/Settings navigation passed using synthetic data.
- No horizontal overflow at 390px on empty Jobs, populated list/detail, or Settings. Error-level browser logs were empty in the inspected app and synthetic Jobs session.
- Focused region review used the reported search control; full captures were sufficiently readable for the remaining flat-layout decisions.

The preview remains at http://127.0.0.1:8080/. Temporary viewport overrides were reset. This QA does not claim live model evaluation, résumé generation, collection configuration, notifications, or deployment verification.
