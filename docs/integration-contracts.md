# Integration evidence

The lockfile pins the installed dependency graph, including ats-scrapers 0.3.0, python-jobspy 1.2.0 and Apprise 1.13.1. Resume Matcher is built from source commit `63fc344a9a59a79db6fa9d96aff188dc9faf545b`; its API is independent of the pipeline's Python runtime.

| Integration | Contract and evidence |
|---|---|
| ATS, directory, JobSpy | [Collection contracts](collection-contracts.md): live Ashby inventory and directory reads, source-inspected adapters, timeout and coverage tests. A live narrow Indeed query returned no rows, so its posting-field contract remains verified through fixtures/source only. |
| Matching and Apprise | [Matching/alert contracts](matching-alerts-contracts.md): conservative constraints, structured evidence, installed attachment API, mocked acceptance/failure tests. |
| Resume Matcher | [Resume contracts](resume-contracts.md): exact endpoint sequence, pinned source, synthetic HTTP integration, crash reconciliation, factual and PDF validation. |
| Coordinator and Dot | SQLite observations and queue transitions, opening-before-PDF dependency, content/profile freshness checks, terminal failure notices, atomic local outbox and native thread relay. The outbox confirms local handoff, not human receipt. |

Live model inference, generated-template visual inspection, attachment receipt and the sustained latency trial are distinct acceptance gates. Passing offline tests does not establish those results.
