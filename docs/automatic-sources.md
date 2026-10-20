# Automatic company sources

After onboarding, the discovery worker refreshes the public company directory daily.
It queues every resolvable Greenhouse, Lever, and Ashby board, with no total company
limit. These are the adapters whose complete inventories the application validates.
Other ATS providers in the directory are not automatically enabled.

The worker validates up to 40 candidates per batch, spaces requests by provider,
and resumes after a five-minute lease. Successful boards become ordinary saved
sources with daily schedules distributed across the day. Their collection, pause,
run history, and deletion use the existing Sources controls. Deleting a discovered
source does not cause the directory to recreate it. Paused sources remain paused.
Failed boards retry no sooner than the next day. Directory failures retry after
ten minutes and do not discard existing sources or pending candidates.

Saved job-site searches also recognize employer ATS links in returned postings and
queue those boards for validation. Company names are never used to guess URLs.
Dotted board tokens are supported. Regional Lever URLs that the saved-source
adapter cannot preserve remain unsupported rather than being redirected.

Settings > Sources shows automatic discovery progress and directory errors. Stop
job ingestion pauses discovery as well as collection, including a stop that occurs
during board validation. Restarting the app retains pending candidates, schedules,
and completed validations in SQLite. No external timer or manually imported job
batch is required.

Automatic discovery and saved-source collection work without local company YAML files.
