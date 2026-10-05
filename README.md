# internship-pipeline

A personal internship search pipeline that detects relevant SWE, product management, ML/AI and data science openings, prepares a tailored resume, and sends the details and PDF to the user.

**Status:** planning and repository scaffold. The application is not implemented or deployed.

## Planned workflow

```text
ats-scrapers + JobSpy → normalize and deduplicate → relevance and eligibility
                                                   ├─ Apprise opening alert
                                                   └─ Resume Matcher → validated PDF → Apprise
```

Direct company checks prioritize speed; broader JobSpy searches expand coverage. Collection runs independently of resume generation so a slow model cannot delay discovery.

## Start here

- [Stepped implementation plan](docs/implementation-plan.md) — ordered work, dependencies and acceptance checks.
- [Design and operating targets](docs/design.md) — architecture, matching, generation, delivery and recovery decisions.
- [Agent guidance](AGENTS.md) — repository conventions.

Implement the steps in order. Step 6 delivers the first complete workflow; steps 7–12 make it continuous, broaden coverage and validate operating targets.

## Selected components

| Responsibility | Component |
|---|---|
| Direct company job feeds | [ats-scrapers](https://github.com/kalil0321/ats-scrapers) |
| Wider job-board discovery | [JobSpy](https://github.com/speedyapply/JobSpy) |
| Tailored resume and PDF | [Resume Matcher](https://github.com/srbhr/Resume-Matcher) |
| Alerts and attachments | [Apprise](https://github.com/caronc/apprise) |
| Coordination and persistent state | Python, SQLite and Docker Compose |

## Operating targets

- Poll priority company boards every 2–5 minutes after provider-specific validation.
- Poll other monitored boards every 10–15 minutes; run broad searches every 30–60 minutes.
- Send an opening alert within 30 seconds of a relevance decision.
- Target a resume-ready notification within two minutes of that decision at the 95th percentile, subject to measurement with the chosen model and host.

These are proposed targets, not publication-to-delivery guarantees. Employer feeds and job boards can introduce delays before a posting becomes visible.

## Personal setup

Live operation requires a factual master resume, target locations and term, eligibility details, a notification destination, an LLM provider, and an always-on host. None of these credentials or private documents belongs in Git. Use synthetic fixtures in committed tests and keep local personal inputs under ignored paths.

The user reviews the resume and submits the application. Resume generation never marks an application as submitted.
