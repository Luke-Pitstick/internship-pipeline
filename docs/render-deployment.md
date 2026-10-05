# Render deployment

The deployment uses one background worker for the five supervised pipeline roles,
and one private Resume Matcher service for structured resume storage and PDF export.
Both use persistent disks. The worker's SQLite database stays on one service;
there is no shared disk between Render services.

`render.yaml` describes the resources. Validate changes before deploying:

```sh
render blueprints validate render.yaml --workspace YOUR_WORKSPACE_ID --output json
```

Both services use Standard instances (1 CPU, 2 GB RAM). At the rates verified on
2026-10-05, their combined compute is $50/month and 7 GB of disks is $1.75/month,
excluding workspace fees, tax, build overages and bandwidth overages. Resource
creation is separate from activating the pipeline.

## Provisioning

The worker starts in a waiting state until `/var/data/activated` exists. Before
creating that marker, provision and verify:

1. `/var/data/config/settings.yaml` from `deploy/settings.yaml`, with
   `RESUME_MATCHER_URL` set to the renderer's actual private hostname and port.
2. `/var/data/config/companies.yaml` containing verified company boards, or `[]`
   when seeding the discovery directory through the CLI.
3. `/var/data/private/profile.yaml` containing the factual candidate profile and
   `master_resume_path: /var/data/private/master-resume.pdf`.
4. The actual master PDF at that path, with private directory/file permissions.
5. A subscription login through `codex login --device-auth` in the worker's SSH
   session, with `CODEX_HOME=/var/data/codex`. Complete the account authorization
   yourself. Never commit authentication caches or put them in image layers.
6. A successful structured-output Codex probe and a synthetic renderer/PDF test.

The installed CLI chooses its default model. Desktop model labels are not assumed
to be valid CLI model names. Subscription limits still apply. Only one resume
worker performs inference at a time; collectors run independently.

Seed discovery once, establish the first observation baseline, and then explicitly
review the backlog if desired. Initial inventory is not presented as newly posted.
No deployment operation marks an application as submitted.

## Dot delivery

The local relay must download remote events before its existing sheet/notification
processing. Authorize this Mac's public SSH key in Render, then run:

```sh
python3 scripts/sync_render_outbox.py \
  --ssh-address SERVICE_ID@ssh.oregon.render.com \
  --repo /absolute/path/to/internship-pipeline
```

This read-only remote transfer verifies event identities and artifact paths,
downloads PDFs into `artifacts/render/`, and atomically publishes complete events
to `data/dot-outbox`. Existing relay checkpoints remain independent of the sync.
Dot still requires the local host and Codex to be available; collection continues
on Render while it is offline. Resume PDFs are not uploaded to Google Drive.

## Verification

Check Render deploy status, then inspect runtime logs for the worker's waiting
message. A live deployment in that state is infrastructure only. After activation,
verify all five roles, increasing collection observations, a factual match, a ready
PDF, a successful SSH sync, and the separate Google Sheets and Dot checkpoints.
Keep synthetic jobs outside the production database and tracker.
