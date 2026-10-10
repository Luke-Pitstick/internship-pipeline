# Username/password owner setup

The first-run account form contains only username and password. Ownership still requires a single-use, random secret, but the installer obtains it through the owned local container and opens a private URL automatically. Headless installation prints that link; `--no-open` suppresses automatic browser launch. `internship-pipeline open` issues a new link while an unclaimed installation is running and opens ordinary sign-in once it is claimed.

The secret travels in `#setup=...`, so it is absent from HTTP request targets and referrers. The browser immediately replaces that history entry, retains the secret in tab session storage across reloads, and removes it after claim or when an existing owner is detected. The secret is never rendered as a field or embedded in page content. SQLite retains only its digest. Issuing a new link invalidates the previous one; creating or replacing an owner still requires the atomic claim or separate offline owner recovery. Installer output and startup setup links remain private.

`setup-link` runs with the image user and a shared installation lock. It can safely rotate an unclaimed secret while the application runs; it cannot change an existing owner. The host checks container/volume ownership and validates that the returned URL matches its saved origin before opening it. No public endpoint issues setup authority.

## Validation on October 10, 2026

- The complete backend regression passed: 961 tests. Six subsequently added host-opening cases also passed in the eight-case targeted opening run.
- All 39 browser tests passed across all ten configurations, including account creation, first-run guided setup, sign-in/logout and existing settings/workflows. The account test checks two fields, absent/invalid links, fragment removal, reload retention, no secret in request URLs/page text, and removal after claim.
- Desktop and 390-pixel mobile screenshots were inspected; the form fits without horizontal overflow.
- Ruff, strict mypy, Svelte checking, production build and bundle budget passed. Compressed JavaScript is 80,499 gzip bytes against a 200,000-byte budget.
- Actual-container and publication evidence is recorded separately; source/native/browser checks alone do not certify a published release.
