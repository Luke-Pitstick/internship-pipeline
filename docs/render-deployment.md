# Render deployment

`render.yaml` builds the same single application image used by Compose. It serves Svelte assets and FastAPI on port 8080 while the existing supervisor manages configured worker roles. Mount the persistent disk at `/var/data` and set `PIPELINE_ORIGIN` to the exact public HTTPS origin, for example `https://your-service.onrender.com`. This enables Secure session cookies and same-origin mutation checks. The blueprint checks `/readyz`; `/healthz` only reports process liveness.

A fresh deployment serves owner setup immediately. Read the generated one-time setup
token from startup logs and claim the instance in its browser UI. No profile or model
credential is needed for account setup. Token rotation and owner recovery are **offline**
operations: the active service shell cannot perform them while the supervisor holds the
installation lock. Stop the service and every worker, then use the exact deployed image's
maintenance CLI with the same preserved disk mounted at `/var/data`, networking disabled,
and a private interactive terminal; run `setup-token --data-dir /var/data` before claim or
`recover-owner --data-dir /var/data` after claim. Restart only after success and verify
sign-in. Recovery revokes all browser sessions and preserves application data.

This requires a platform facility that can stop all disk writers and attach that disk
exclusively to the same image for maintenance. This repository has not verified such a
Render procedure. If that capability is unavailable, use an operator-supported stopped
disk recovery/export procedure and the same-image recovery instructions in
[deployment](deployment.md) and [T17](t17-operations.md). Do not run recovery in the
active service shell or create a replacement empty disk. Render recovery remains an
open platform acceptance requirement.

Preserve existing data. Accounts and sessions live in `/var/data/identity.sqlite3`, job
storage defaults to `/var/data/state.sqlite3`, and artifacts live in `/var/data/artifacts`.
Optional `/var/data/config/settings.yaml` supplies current operational source/path
settings only; the shipped `deploy/settings.yaml` uses the strict current loader.
Candidate facts, filters, reviewed imports and model connections are edited in
authenticated browser Settings and saved in SQLite. Keep the exact credential key,
databases, uploads/provenance, configuration and artifacts together in recovery material.

After owner claim, saved-search, email and Sheets workers process configured queued work.
Operational company/search configuration enables collection independently of candidate,
model and delivery readiness. A confirmed profile enables master/tailored résumé work;
a tested current Jev connection enables matching. General-LLM document generation uses
the saved tested model connection and supported confirmed facts. Saving a credential does
not test it, invoke a model or send notifications. The supervisor notices newly ready
roles without restart; restart after changing operational YAML. No Codex CLI/login or
local relay is part of the deployed worker path.

See [deployment](deployment.md) for recovery and private-volume handling and [dashboard](dashboard.md) for current UI behavior. This change was not deployed to a live Render service. The SSH outbox relay has been removed. Optional email and Google Sheets are configured in authenticated Settings and processed by independent integration workers.
