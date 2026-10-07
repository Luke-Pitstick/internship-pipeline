# Implementation ownership and shared contracts

Baseline: `src/internship_pipeline/models.py`. Changes to shared models and package configuration are owned by the parent coordinator. Request additions rather than changing those files in worker branches.

- Parent: package/config, SQLite storage and durable queue, orchestration, CLI, process roles, deployment/CI, integration tests, final docs.
- Collection worker: `sources/`, `normalization.py`, `scheduler.py`, `discovery.py`, and their focused tests/contract docs.
- Resume worker: `resumes/` and its focused tests/contract docs.
- Matching/integration workers: `assessments.py`, `email_integrations.py`, `sheets_integration.py`, and focused tests/contract docs.

Each worker has an independent Git worktree and must make regular commits after coherent validated changes. Stage only owned files, never secrets or generated private data. All workers are operating concurrently; do not revert others' work. Communicate contract changes to the parent.

Required Python interfaces:

```python
# sources/ats.py
async def fetch_company(company: Company, timeout: float = 30) -> FetchResult: ...
# sources/jobspy.py -- isolate blocking calls and impose a wall-clock timeout
def fetch_search(query: SearchQuery, timeout: float = 60) -> FetchResult: ...
# normalization.py
def canonical_url(url: str) -> str: ...
def content_hash(posting: SourceJob) -> str: ...
# assessments.py
class Assessments:
    def evaluate(self, job_id: str, expected_identity: str | None = None) -> None: ...
# resumes/tailored.py
class TailoredResumes:
    def request(self, job_id: str, profile_revision: int, model_revision: int,
                *, automatic: bool = False) -> dict[str, Any]: ...
    def process_next(self) -> bool: ...
# generation_policy.py
class GenerationPolicies:
    def reconcile(self) -> int: ...
# email_integrations.py
class EmailIntegrations:
    def schedule(self, now: float | None = None) -> int: ...
    def process_next(self) -> bool: ...
# sheets_integration.py
class SheetsIntegration:
    def process_next(self) -> bool: ...
```

Keep source imports lazy so offline tests and the core CLI work without optional scraper dependencies. Private configuration and credentials are supplied by environment/local files and are not committed. No external messages, deployments, account changes or applications are authorized during worker tests; use mocked integration transports and synthetic fixtures. The user authorized code implementation, regular commits and the existing private GitHub repository.

Every handoff includes owned files, commits, tests and their results, integration notes, limitations, and a final status. Never claim a live provider/model/delivery/deployment test passed unless actually executed.
