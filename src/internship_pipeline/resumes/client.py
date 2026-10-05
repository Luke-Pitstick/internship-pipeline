"""Narrow client for Resume Matcher 1.3's source-verified API."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

UPSTREAM_REVISION = "63fc344a9a59a79db6fa9d96aff188dc9faf545b"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ResumeMatcherError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, ambiguous: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.ambiguous = ambiguous


class ResumeReconciliationRequired(ResumeMatcherError):
    """A remote write may exist; human reconciliation is safer than duplication."""


class ResumeMatcherClient:
    def __init__(
        self, base_url: str, timeout: float = 30, *, transport: httpx.BaseTransport | None = None
    ):
        self.timeout = timeout
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self.deadline: float | None = None

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        remaining = self.timeout
        if self.deadline is not None:
            remaining = min(remaining, self.deadline - time.monotonic())
        if remaining <= 0:
            raise ResumeMatcherError("Resume generation deadline exceeded", retryable=True)
        mutation = method != "GET"
        try:
            with self.http.stream(method, "api/v1/" + path, timeout=remaining, **kwargs) as resp:
                if resp.status_code >= 400:
                    status = resp.status_code
                    raise ResumeMatcherError(
                        f"Resume Matcher {method} {path.split('?')[0]} returned HTTP {status}",
                        retryable=status in {408, 429} or status >= 500,
                        ambiguous=mutation and (status in {408, 429} or status >= 500),
                    )
                if resp.status_code >= 300:
                    raise ResumeMatcherError(
                        "Unexpected Resume Matcher redirect", ambiguous=mutation
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ResumeMatcherError(
                            "Resume Matcher response too large", ambiguous=mutation
                        )
                    if self.deadline is not None and time.monotonic() > self.deadline:
                        raise ResumeMatcherError(
                            "Resume generation deadline exceeded",
                            retryable=True,
                            ambiguous=mutation,
                        )
                    chunks.append(chunk)
                return httpx.Response(
                    resp.status_code, headers=resp.headers, content=b"".join(chunks)
                )
        except httpx.HTTPError as exc:
            raise ResumeMatcherError(
                "Resume Matcher transport failed", retryable=True, ambiguous=mutation
            ) from exc

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            result = self._request(method, path, **kwargs).json()
            if not isinstance(result, dict):
                raise ValueError("Expected object")
            return result
        except ValueError as exc:
            raise ResumeMatcherError(
                "Invalid Resume Matcher response", ambiguous=method != "GET"
            ) from exc

    def import_master(self, resume_data: dict[str, Any]) -> str:
        data = self._json(
            "POST", "resume-wizard/finalize", json={"state": {"resume_data": resume_data}}
        )
        return self._id(data.get("resume_id"))

    @staticmethod
    def _id(value: Any) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ResumeMatcherError("Missing or invalid remote ID", ambiguous=True)
        return value

    def get_resume(self, resume_id: str) -> dict[str, Any]:
        data = self._json("GET", "resumes", params={"resume_id": resume_id}).get("data")
        if not isinstance(data, dict):
            raise ResumeMatcherError("Invalid resume fetch payload")
        return data

    def upload_job(self, description: str, master_id: str) -> str:
        data = self._json(
            "POST", "jobs/upload", json={"job_descriptions": [description], "resume_id": master_id}
        )
        ids = data.get("job_id")
        if not isinstance(ids, list) or len(ids) != 1:
            raise ResumeMatcherError("Invalid job upload payload", ambiguous=True)
        return self._id(ids[0])

    def publish_tailored(
        self, key: str, master_id: str, job_id: str, resume_data: dict[str, Any], title: str
    ) -> dict[str, Any]:
        data = self._json(
            "POST",
            "resumes/import-tailored",
            json={
                "generation_key": key,
                "master_id": master_id,
                "job_id": job_id,
                "resume_data": resume_data,
                "title": title,
            },
        )
        self._id(data.get("resume_id"))
        return data

    def job_context(self, resume_id: str) -> dict[str, Any]:
        return self._json("GET", f"resumes/{resume_id}/job-description")

    def download_pdf(self, resume_id: str, template: str) -> bytes:
        response = self._request(
            "GET", f"resumes/{resume_id}/pdf", params={"template": template, "pageSize": "A4"}
        )
        if response.headers.get("content-type", "").split(";")[0] != "application/pdf":
            raise ResumeMatcherError("Resume Matcher returned a non-PDF download")
        return response.content
