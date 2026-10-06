# Internship Pipeline frontend

The SvelteKit 3/Svelte 5/TypeScript application builds static assets for the FastAPI application. Jobs are at `/`; Settings is a separate page at `/settings/`. Private state comes from authenticated API requests after hydration and is never embedded in prerendered HTML. A fresh account displays no synthetic jobs or profile defaults.

From `web/`:

```sh
rtk npm ci
rtk npm run check
rtk npm run build
rtk npm test
rtk npm run measure
```

`npm test` starts a temporary FastAPI process at `http://127.0.0.1:4174`, uses an isolated temporary database and synthetic owner credentials, drives Chromium through claim/login/logout/settings, and stops the server. Install the root Python dependencies first (`uv sync --frozen`); tests use `../.venv/bin/python`. Chromium can be installed with `npm exec playwright -- install chromium`. Test screenshots and the ephemeral setup-token fixture stay in ignored `test-results/`.

Production assets are under ignored `build/`; the Python application serves them on the same origin as `/api`. Static preview alone cannot provide authentication. For local application development, build first, then run the Python bootstrap with `PIPELINE_DATA_DIR` set to an ignored temporary development directory, `PIPELINE_WEB_DIR` set to the absolute `web/build` path, `PIPELINE_ORIGIN=http://localhost:8080`, and `PORT=8080`. Never point development or tests at private production data.

`src/lib/api.ts` is instantiated by each browser layout and passed through Svelte context, avoiding shared server state. The original prototype worker/session, invented opportunities, timer-driven search progress, and fake settings saves have been removed. The job-board design and explicit Mark as applied/Undo/date behavior remain. Full server pagination, authoritative Jev scores, editable settings, and search controls are future tasks; current UI copy makes these limits explicit.

T01 design references and historical measurements remain under `design/` and `reports/`. See [`../docs/t03-container-owner-setup.md`](../docs/t03-container-owner-setup.md) for current verification and limits.
