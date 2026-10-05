"""External contract checks against an explicitly supplied pinned upstream checkout."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

UPSTREAM = os.environ.get("RESUME_MATCHER_SOURCE")
if not UPSTREAM:
    pytest.skip(
        "Set RESUME_MATCHER_SOURCE to run pinned upstream contracts", allow_module_level=True
    )

pytest.importorskip("sqlalchemy")
httpx = pytest.importorskip("httpx")
FastAPI = pytest.importorskip("fastapi").FastAPI
sys.path.insert(0, str(Path(UPSTREAM) / "apps/backend"))
from app.database import Database  # noqa: E402
from app.schemas.models import ResumeData, normalize_resume_data  # noqa: E402


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    native = types.ModuleType("app.main")
    native.app = FastAPI()
    monkeypatch.setitem(sys.modules, "app.main", native)
    path = Path(__file__).parents[1] / "deploy/resume-matcher/pipeline_resume_api.py"
    spec = importlib.util.spec_from_file_location("pipeline_resume_contract", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    module.db = Database(tmp_path / "contract.sqlite")
    return module


async def seed(publisher):
    raw = json.loads((Path(__file__).parent / "fixtures/resume_master.json").read_text())
    data = ResumeData.model_validate(normalize_resume_data(raw)).model_dump(mode="json")
    master = await publisher.db.create_resume_atomic_master(
        content=json.dumps(data),
        content_type="json",
        processed_data=data,
        processing_status="ready",
        title="Synthetic master",
    )
    job = (await publisher.db.create_jobs(["Synthetic Python internship"], master["resume_id"]))[0]
    return {
        "generation_key": "a" * 64,
        "master_id": master["resume_id"],
        "job_id": job["job_id"],
        "resume_data": data,
        "title": "Synthetic draft",
    }


def test_concurrent_replay_creates_one_child_and_no_application(publisher):
    async def exercise():
        try:
            payload = await seed(publisher)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=publisher.app), base_url="http://synthetic"
            ) as client:
                responses = await asyncio.gather(
                    *[
                        client.post("/api/v1/resumes/import-tailored", json=payload)
                        for _ in range(6)
                    ]
                )
            assert [r.status_code for r in responses] == [200] * 6
            assert len({r.json()["resume_id"] for r in responses}) == 1
            assert len(await publisher.db.list_resumes()) == 2
            assert await publisher.db.list_applications() == []
        finally:
            await publisher.db.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["payload", "title", "job"])
def test_key_conflicts_fail_without_new_rows(publisher, change):
    async def exercise():
        try:
            payload = await seed(publisher)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=publisher.app), base_url="http://synthetic"
            ) as client:
                first = await client.post("/api/v1/resumes/import-tailored", json=payload)
                assert first.status_code == 200
                changed = copy.deepcopy(payload)
                if change == "payload":
                    changed["resume_data"]["summary"] = "Changed synthetic summary"
                elif change == "title":
                    changed["title"] = "Changed title"
                else:
                    changed["job_id"] = "different-job"
                response = await client.post("/api/v1/resumes/import-tailored", json=changed)
            assert response.status_code == 409
            assert len(await publisher.db.list_resumes()) == 2
        finally:
            await publisher.db.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["contact", "identity", "repeated", "job", "missing"])
def test_invalid_imports_do_not_create_a_child(publisher, change):
    async def exercise():
        try:
            payload = await seed(publisher)
            expected = 422
            if change == "contact":
                payload["resume_data"]["personalInfo"]["email"] = "invented@example.test"
            elif change == "identity":
                payload["resume_data"]["workExperience"][0]["company"] = "Invented employer"
            elif change == "repeated":
                payload["resume_data"]["workExperience"] *= 2
            elif change == "job":
                other = (await publisher.db.create_jobs(["Other job"], "other-master"))[0]
                payload["job_id"] = other["job_id"]
            else:
                payload["master_id"] = "missing-master"
                expected = 404
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=publisher.app), base_url="http://synthetic"
            ) as client:
                response = await client.post("/api/v1/resumes/import-tailored", json=payload)
            assert response.status_code == expected
            assert len(await publisher.db.list_resumes()) == 1
        finally:
            await publisher.db.close()

    asyncio.run(exercise())


def test_deleted_child_is_not_silently_recreated(publisher):
    async def exercise():
        try:
            payload = await seed(publisher)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=publisher.app), base_url="http://synthetic"
            ) as client:
                first = await client.post("/api/v1/resumes/import-tailored", json=payload)
                assert first.status_code == 200
                await publisher.db.delete_resume(first.json()["resume_id"])
                response = await client.post("/api/v1/resumes/import-tailored", json=payload)
            assert response.status_code == 409
            assert len(await publisher.db.list_resumes()) == 1
        finally:
            await publisher.db.close()

    asyncio.run(exercise())
