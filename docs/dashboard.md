# Local Render dashboard

Run from the repository root with Python 3.12 or newer:

```sh
python3 scripts/render_dashboard.py
```

Open <http://127.0.0.1:8765>. The default SSH address is the deployed Oregon
pipeline worker. Override it with `--ssh-address USER@ssh.REGION.render.com` or
choose another local port with `--port 8766`. Authorize your usual Mac SSH public
key in Render first. The dashboard uses that key, accepts a host key on first
connection, and rejects changed keys. No Python dependencies are required.

The page refreshes every 30 seconds and has a manual refresh button. Concurrent
requests share a cache; manual refreshes are limited to once per five seconds.
SSH connections time out after 20 seconds. Failed reads retain the last successful
snapshot with an explicit offline label and its observation time. Snapshots older
than 90 seconds are stale.

Readiness shows file presence for activation, settings, companies, the candidate
profile, master PDF, and Codex login. The candidate profile is loaded only on
Render for deterministic relevance screening; its contents never leave Render.
The other provisioning files are checked for existence only. A login file does
not prove the session remains valid. Worker indicators inspect process arguments
locally on Render but return only five role-presence flags, never command lines.
Process presence does not prove inference or delivery succeeds.
The PDF renderer card checks the fixed private service's health endpoint with a
three-second timeout; it never creates resumes or returns its response contents.

SQLite opens with `mode=ro` and `query_only=ON`, without creating or migrating its
database. Remote Python uses `/app/.venv/bin/python` and imports only profile
configuration, typed records, and the shared deterministic matcher. It never
invokes LLM assessment, collection, resume generation, or delivery. The view
includes database counts, task counts
by role and state, oldest pending/running work, source attempt/success/due times
and failure counts, and up to twenty preliminary profile matches. Source rows are limited
to 100; summary counts cover all sources. First observation and source publication
times remain separate, and backlog events retain their label. "Recorded
deliveries" means database delivery records; local Dot relay and Google Sheets
completion are outside this view.

The default job section screens the newest 1,000 open collected listings using
the current candidate profile and deployed matcher. A shown job needs an accepted
deterministic assessment, supporting candidate skill facts, and an explicit
internship/co-op title or structured employment type. Confirmed eligibility
conflicts are excluded. Counts explicitly state this bounded scope rather than
claiming coverage of all collected listings. The raw collected count includes
irrelevant inventory and is not a recommendation count. Missing/invalid profiles
or any matcher failure show no recommendation rows; raw listings never replace
the filtered view. Displayed fit is preliminary, and a count of remaining review
questions does not establish full eligibility or end-to-end approval.

No credentials, candidate facts or identifiers, resume contents, task payloads, job descriptions,
raw error messages, or full process commands enter the response. There are no
production writes, collection calls, model calls, or operational controls. The
server binds only `127.0.0.1`, rejects unrelated Host headers, and uses no external
scripts, styles, fonts, or analytics.
