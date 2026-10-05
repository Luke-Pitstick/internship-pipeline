"""Pinned Resume Matcher app with one idempotent structured-publishing route."""

from __future__ import annotations

import json
from typing import Any

from app.database import db
from app.main import app
from app.models import Improvement
from app.schemas.models import ResumeData, normalize_resume_data
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError


class ImportTailoredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    master_id: str = Field(min_length=1, max_length=100)
    job_id: str = Field(min_length=1, max_length=100)
    resume_data: ResumeData
    title: str = Field(min_length=1, max_length=300)


def _check_source(source: dict[str, Any], candidate: dict[str, Any]) -> None:
    personal = source.get("personalInfo", {})
    result_personal = candidate.get("personalInfo", {})
    for key in ("name", "email", "phone", "location", "website", "linkedin", "github"):
        if (personal.get(key) or "") != (result_personal.get(key) or ""):
            raise HTTPException(422, "Structured import changed a protected contact field")
    fields = {
        "workExperience": ("title", "company", "years", "location"),
        "education": ("institution", "degree", "years"),
        "personalProjects": ("name", "role", "years", "github", "website"),
    }
    for section, keys in fields.items():
        originals = [tuple(row.get(key) or "" for key in keys) for row in source.get(section, [])]
        for row in candidate.get(section, []):
            identity = tuple(row.get(key) or "" for key in keys)
            if identity not in originals:
                raise HTTPException(422, "Structured import changed a protected factual identity")
            originals.remove(identity)


async def _replay(request: ImportTailoredRequest, content: str) -> dict[str, Any] | None:
    async with db._session() as session:
        relation = await session.get(Improvement, "pipeline-" + request.generation_key)
        if relation is None:
            return None
        if relation.original_resume_id != request.master_id or relation.job_id != request.job_id:
            raise HTTPException(409, "Generation key belongs to different inputs")
        resume = await db.get_resume(relation.tailored_resume_id)
        if resume is None:
            raise HTTPException(409, "Published resume was deleted; inspect before retry")
        if resume["content"] != content or resume.get("title") != request.title:
            raise HTTPException(409, "Generation key belongs to a different structured payload")
        return {
            "resume_id": resume["resume_id"],
            "job_id": request.job_id,
            "parent_id": request.master_id,
            "processing_status": "ready",
        }


@app.post("/api/v1/resumes/import-tailored")
async def import_tailored(request: ImportTailoredRequest) -> dict[str, Any]:
    candidate = ResumeData.model_validate(
        normalize_resume_data(request.resume_data.model_dump(mode="json"))
    ).model_dump(mode="json")
    content = json.dumps(candidate, sort_keys=True, ensure_ascii=False)
    replay = await _replay(request, content)
    if replay is not None:
        return replay
    source = await db.get_resume(request.master_id)
    job = await db.get_job(request.job_id)
    if source is None or job is None:
        raise HTTPException(404, "Master resume or job does not exist")
    if not source.get("is_master") or source.get("processing_status") != "ready":
        raise HTTPException(422, "Structured import requires a ready factual master")
    if job.get("resume_id") != request.master_id:
        raise HTTPException(422, "Job belongs to a different factual master")
    if not isinstance(source.get("processed_data"), dict):
        raise HTTPException(422, "Master lacks structured factual content")
    _check_source(source["processed_data"], candidate)
    try:
        resume = await db.create_tailored_resume(
            request_id="pipeline-" + request.generation_key,
            original_resume_id=request.master_id,
            job_id=request.job_id,
            resume_fields={
                "content": content,
                "content_type": "json",
                "filename": f"pipeline-{request.generation_key}.json",
                "is_master": False,
                "is_default_master": False,
                "parent_id": request.master_id,
                "processed_data": candidate,
                "processing_status": "ready",
                "title": request.title,
            },
            improvements=[],
        )
    except IntegrityError:
        replay = await _replay(request, content)
        if replay is None:
            raise
        return replay
    return {
        "resume_id": resume["resume_id"],
        "job_id": request.job_id,
        "parent_id": request.master_id,
        "processing_status": "ready",
    }
