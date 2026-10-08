# Security policy

This checkout is release preparation. No version is currently advertised as a
supported public release. When a candidate passes the release gates, its release
notes must name the exact supported version, image digest and host/runtime matrix.
Earlier candidates and source snapshots have no promised security maintenance
period; this policy does not create a response-time or update guarantee.

## Reporting a vulnerability

The proposed private reporting route is GitHub's
[Report a vulnerability form](https://github.com/Luke-Pitstick/internship-pipeline/security/advisories/new).
The repository was private on October 8, 2026, and the private-reporting API returned
404. This route is **not yet verified or enabled for public reports**. Before making
a public release, the owner must make the repository public, enable private
vulnerability reporting, confirm that an outside account can reach the form, and
ensure the maintainer receives its notifications. GitHub describes this feature for
public repositories in its
[configuration guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

Until that gate passes, no public private-reporting route is verified here. There
is no separately configured security email address. Don't put credentials, setup
tokens, real résumés, personal
candidate facts or exploit details in public issues or discussions.

A private report should identify the source revision or image digest, affected
host/runtime and minimal reproduction steps using synthetic data, explain the
impact, and include redacted diagnostics. Test only installations and accounts
you are authorized to use. Coordinate disclosure through the verified private
route after it is available.
