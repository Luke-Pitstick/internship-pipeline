# Recruiter and recruiting-contact discovery

Research date: October 6, 2026.

Finding useful recruiting contacts is feasible as an optional enrichment feature. Reliably identifying two active recruiters who own every posting is not a promise the available public interfaces support. The product should show up to two evidence-backed contacts, explain their connection to the job, and allow an empty result.

## What the sources support

| Source | What we can obtain | Practical limit |
| --- | --- | --- |
| Public job descriptions and ATS feeds | Explicit names, emails, or contact links if the employer includes them in the description or exposed metadata. | The documented Greenhouse, Lever, and Ashby public posting schemas do not supply a standard recruiter-owner field. Greenhouse allows employer-selected custom metadata. This is an inference from their documented fields, not a claim that descriptions never contain contacts. |
| Employer careers, early-career, and recruiting-event pages | Published recruiting channels and sometimes named recruiting staff with relevant program or regional context. | A company contact is not automatically the owner of an individual requisition, and an undated page does not prove recent activity. |
| Public web search | Candidate source pages and publicly indexed profile links. | Search results are discovery leads; validate the underlying source and its date rather than treating a snippet as proof of current employment. |
| Optional Hunter enrichment | Domain-associated professional emails, names, positions, source URLs and dates, and email-verification results when available. | Deliverability and source freshness do not prove current employment, job ownership, or willingness to answer. Inferred addresses need different labeling from published addresses. |

ATS evidence: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), [Lever Postings API](https://github.com/lever/postings-api), [Ashby public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api). These are public posting interfaces; authenticated employer APIs are a separate access path and should not be assumed available to applicants.

A concrete example of an employer-published channel is [Microsoft Japan's New Graduate Recruitment Office](https://www.microsoft.com/ja-jp/mscorp/college/msd-contact), which publishes a recruiting email for inquiries unresolved by its FAQ. That supports a scoped program contact, not a named recruiter for every Microsoft job. [Microsoft's virtual recruiting events page](https://careers.microsoft.com/v2/global/en/virtualevents) also names university recruiting staff, illustrating a discovery source whose age and relevance still need checking.

[Hunter's API documentation](https://hunter.io/api-documentation/v2) supports domain search with sources and email verification. Its [Domain Search explanation](https://help.hunter.io/en/articles/1922737-what-information-can-i-find-with-the-domain-search) distinguishes public and inferred sources. Its [verification guidance](https://help.hunter.io/en/articles/1830792-domain-search-find-emails-from-companies) says accept-all and unknown mailboxes cannot be fully confirmed; even high confidence is not a delivery guarantee. Make enrichment optional and budgeted rather than looking up every collected job.

## LinkedIn boundary

LinkedIn's [Profile API](https://learn.microsoft.com/en-gb/linkedin/shared/integrations/people/profile-api?view=li-lms-2026-02) is restricted to approved developers, and access to other members requires identifiers available through limited-access APIs. It also prohibits storing Profile API data for members other than the authenticated member. This is not a general recruiter-search API for this pipeline.

LinkedIn's [prohibited-software policy](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions) prohibits scraping profiles and unauthorized automated activity, including messages. Build around employer-published sources, permitted search/enrichment services, and manually opened profile links. A LinkedIn link does not imply that the user can DM that member; leave outreach to the user in LinkedIn.

## Evidence shown to users

Keep these claims separate instead of collapsing them into an “active recruiter” score:

- **Job connection:** An explicit reference to this posting or requisition supports “listed contact for this job.” A matching company, discipline, region, or early-career program supports “potential recruiting contact.”
- **Employment evidence:** Store the source supporting the company and role, plus when it was checked. A current-looking title alone does not establish job ownership.
- **Activity evidence:** Show a dated, relevant hiring announcement or recruiting event when available. A page fetched today is not evidence that its author recruited today; otherwise show “activity unknown.”
- **Email evidence:** Show published versus provider-inferred provenance, verification status, and verification date separately. Never construct email addresses from a guessed company naming pattern.

## Recommended first version

1. Extract explicit recruiting contacts from each job's source description during collection, with source attribution. Exclude accessibility, legal, privacy, and technical-support addresses unless their stated purpose is recruiting outreach.
2. Add a **Find contacts** action on a saved or shortlisted job. Search official company recruiting sources, rank exact-job evidence above program/team/region evidence, and show up to two relevant contacts with source links and dates. Include an official recruiting channel when appropriate and label it as a team channel.
3. Cache discoveries by company domain and recruiting scope, then associate them with relevant jobs. Keep this ordinary Python/SQLite enrichment separate from collection so provider errors or exhausted budgets cannot stop job ingestion. Cache empty results too, with a configurable refresh interval.
4. Add an optional provider later for email enrichment and verification, with an API key and usage cap in Settings. Support manual contact additions/corrections, hiding stale suggestions, and user-initiated refresh. Email and LinkedIn actions should open the user's chosen channel; do not send automatically.

Before promising coverage, evaluate a representative sample of the pipeline's actual employers. Record the proportion with any useful contact, exact-job contacts versus company/program contacts, stale or incorrect affiliations, and requests/cost per result. This research reviewed interfaces and examples; it did not run that coverage test or establish accuracy percentages.

## Open-source options

These tools supply discovery or verification components; none of the reviewed projects supplies a maintained database mapping every job to its active recruiters.

- **SearXNG is the best first candidate for public-page discovery.** It is an AGPL-licensed, self-hosted metasearch engine, and its HTTP search API returns JSON when that format is enabled in `settings.yml`. Use it to find employer recruiting pages and source links, then validate those sources with the pipeline's extraction and ranking logic. Many public instances disable JSON, so use an instance you control. It aggregates upstream search services rather than providing an independent recruiter dataset. [Project](https://github.com/searxng/searxng), [Search API](https://docs.searxng.org/dev/search_api.html).
- **Reacher's `check-if-email-exists` is an optional verification component.** It offers a CLI and self-hosted HTTP backend that check email addresses without sending messages. Its container needs outbound port 25; the project also notes that processing more than very small volumes requires SMTP proxies, which adds deployment complexity. It verifies addresses already discovered, not recruiter identity or job relevance. The code uses an AGPL-3.0/commercial dual-license model, so check the chosen integration against the pipeline's license before distribution. [Project and deployment/license notes](https://github.com/reacherhq/check-if-email-exists).
- **theHarvester is an adjacent OSINT tool rather than the preferred tracker dependency.** Its GPL-2.0 project collects domain-associated emails and other evidence from multiple sources, some requiring provider API keys and quotas. Its stated workflow is authorized security reconnaissance, and its current README instructs operators to use targets they own or have permission to test. Its broad security scope and lack of recruiter/job attribution make focused recruiting-page search a simpler fit here. [Project, source catalog, and usage scope](https://github.com/laramies/theHarvester).

Start with SearXNG plus source-backed extraction, keep user-visible evidence and missing results, and add verification only when real results show it is needed. These projects were reviewed through their documentation; they were not installed or benchmarked for this pipeline.
