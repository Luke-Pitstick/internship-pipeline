import asyncio
from pathlib import Path

from internship_pipeline.collection import collect_due, register_targets
from internship_pipeline.models import CandidateProfile, Company, FetchResult, Settings, SourceJob
from internship_pipeline.storage import Store


def test_failed_provider_does_not_block_successful_boards(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "db.sqlite")
    settings = Settings(database_path=store.path)
    profile = CandidateProfile()
    companies = [
        Company(
            id="good", name="Good", careers_url="https://jobs.ashbyhq.com/good", provider="ashby"
        ),
        Company(id="bad", name="Bad", careers_url="https://jobs.lever.co/bad", provider="lever"),
    ]
    register_targets(store, companies, [])

    async def fetch(company, timeout):
        if company.id == "bad":
            return FetchResult(complete=False, error="RateLimited", retry_after_seconds=120)
        return FetchResult(
            jobs=[
                SourceJob(
                    source="ashby",
                    source_id="one",
                    board_id=company.id,
                    company=company.name,
                    title="SWE Intern",
                    description="Python internship.",
                    apply_url="https://example.invalid/good/one",
                )
            ]
        )

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    assert asyncio.run(collect_due(store, profile, settings)) == 1
    assert len(store.list_jobs()) == 1
    targets = {row["id"]: row for row in store.targets()}
    assert targets["company:good"]["last_success"] is not None
    assert targets["company:bad"]["failures"] == 1
    assert store.provider_ready_at("lever") > 0


def test_partial_baseline_still_discovers_future_additions(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.register_target("board", "company", "{}", "workday")
    job = SourceJob(
        source="workday",
        source_id="one",
        board_id="board",
        company="Acme",
        title="SWE Intern",
        description="Internship",
        apply_url="https://example.invalid/one",
    )
    store.ingest(
        "board",
        FetchResult(jobs=[job], complete=False, error="Completeness not audited"),
        "profile",
    )
    second = job.model_copy(update={"source_id": "two", "apply_url": "https://example.invalid/two"})
    store.ingest(
        "board",
        FetchResult(jobs=[second], complete=False, error="Completeness not audited"),
        "profile",
    )
    assert store.health()["tasks"] == {"pending": 1}
    assert all(item.status == "open" for item in store.list_jobs())
