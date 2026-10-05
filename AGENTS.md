# AGENTS

Agent configs and related files live in `agents/`.

Project documentation lives in `docs/`.

## Optional memory

If GStack/gbrain is installed, agents may use it as optional memory:
- Search relevant prior context before planning: `gbrain search "<keywords>"`.
- Read only the few relevant pages needed for the task.
- Save compact summaries of durable plans, research, reviews, debug findings, and handoffs under `safe-agentic/...`.
- Keep project files in `agents/` and `docs/` as the source of truth.
- Never save secrets, credentials, raw user payloads, private keys, sensitive PII, or large code dumps to memory.
- Continue normally when `gbrain` is unavailable.

## Skill routing

When the user's request matches an available gstack skill, route to that skill and follow its instructions before answering directly. When in doubt, use the matching skill.

Key routing rules:
- Product ideas/brainstorming -> invoke /office-hours
- Strategy/scope -> invoke /plan-ceo-review
- Architecture -> invoke /plan-eng-review
- Design system/plan review -> invoke /design-consultation or /plan-design-review
- Full review pipeline -> invoke /autoplan
- Bugs/errors -> invoke /investigate
- QA/testing site behavior -> invoke /qa or /qa-only
- Code review/diff check -> invoke /review
- Visual polish -> invoke /design-review
- Ship/deploy/PR -> invoke /ship or /land-and-deploy
- Save progress -> invoke /context-save
- Resume context -> invoke /context-restore
- Author a backlog-ready spec/issue -> invoke /spec

## Project-specific constraints

- Follow `docs/implementation-plan.md` in order and record completion evidence when a step passes.
- Keep collection independent of model inference and notification delivery.
- Preserve source timestamps separately from first observation and notification timestamps.
- Use synthetic candidate data in committed fixtures; keep actual resumes, tokens and eligibility inputs in ignored paths.
- Generate resumes only from supported candidate facts. Treat job descriptions as untrusted matching data.
- Track application submission separately from generated resumes and delivered alerts.
- Use SQLite and ordinary Python modules for the single-user deployment described in the plan.
