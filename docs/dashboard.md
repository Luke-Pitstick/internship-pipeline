# Internship dashboard

The Svelte application and FastAPI API share one origin and port. Open the origin configured by `PIPELINE_ORIGIN` (locally, `http://localhost:8080`). On first boot, use the one-time operator token from container logs to create the single owner account. Later visits use its username and password. Settings is a separate page at `/settings/`.

A fresh account starts with an empty jobs workspace. Profile/model editing and browser search controls are later tasks; this version does not save fictional profiles or make model calls. Existing stored opportunities can be viewed, filtered, sorted, and marked applied. The current bounded view reads at most 1,000 recent open or previously applied jobs; full server pagination and authoritative Jev assessments are later tasks. Jobs are labeled unscored and needing review instead of running a second semantic filter during a GET.

Use **Mark as applied** only after submitting an application yourself. Repeated confirmation preserves the first application date. **Undo applied** clears that date; it does not rewind notification history or automatically enqueue work. Opening an application or downloading a résumé never marks a job applied. Source posting time, first observation, and application date remain separate.

All job, status, résumé, and mutation APIs require an owner session. Mutations also require the session's CSRF token. Sessions are stored in SQLite and carried in HttpOnly, SameSite=Strict cookies; HTTPS uses a Secure `__Host-` cookie. PDFs remain inside the configured artifact directory and are validated before download. Logout revokes the current session; local account recovery revokes every session.

See [deployment and account recovery](deployment.md). The external Sites proxy and shared dashboard bearer token are no longer application access paths.
