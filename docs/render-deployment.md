# Render deployment

The pipeline runs in one Standard Render web service with a 5 GB persistent disk at /var/data. A supervisor runs the protected results API alongside independent collector, matcher, resume, delivery and discovery processes. SQLite and PDFs stay on this one disk. The obsolete background worker and separate Resume Matcher renderer are suspended.

The service is srv-db23e6rtqb8s73btl8d0 in Luke's Workspace, Oregon. Its public /healthz returns no private information. All data and mutation routes require DASHBOARD_API_TOKEN. The private Sites dashboard stores this credential server-side and proxies job reads, PDF downloads and explicit Mark as applied requests.

## Private provisioning

Place settings and company/search configuration in /var/data/config. Put the verified factual profile in /var/data/private/profile.yaml and the original source in /var/data/private/master-resume.tex. Set master_resume_path to that absolute .tex path. Preserve CODEX_HOME=/var/data/codex and complete codex login --device-auth with the user's subscription; never put login files in Git or image layers.

Set RESUME_MODEL=gpt-6-luna. Set RESUME_GENERATION_PAUSED=1 during source verification and 0 only after an end-to-end generation check. This pause leaves collection, matching and delivery running. Create /var/data/activated after provisioning to start the workers. pdflatex is installed in the pipeline image; it compiles the original and tailored source with shell escape disabled and checks page count, content and overflow.

## Dashboard and relay

See dashboard.md for the private Sites URL and controls. The dashboard and Render collection work without the Mac. The existing Codex relay still depends on the Mac and is not ChatGPT Dot. Its remote source is srv-db23e6rtqb8s73btl8d0@ssh.oregon.render.com; scripts/sync_render_outbox.py downloads complete events and existing PDFs before independent Google Sheets and notification checkpointing. PDFs are not uploaded to Drive.

## Recovery and verification

Stop writers before copying SQLite data, or use the existing database-native backup command. Preserve the original source, factual profile, artifact PDFs and edit plans, and subscription login separately in private storage. Never merge a live database with stale WAL files.

Verify /healthz, unauthorized data rejection, authenticated jobs, PDF download bytes and attachment headers, and worker activity. Applied-state tests use isolated databases and must not mark real applications during QA. Existing non-LaTeX drafts remain labeled as earlier drafts until superseded by verified original-template PDFs.
