"""Load explicit personal configuration without inventing eligibility rules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from internship_pipeline.models import CandidateProfile, Company, SearchQuery, Settings


class ConfigurationError(ValueError):
    pass


def read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read configuration file: {path}") from exc


def load_settings(path: Path | None = None) -> Settings:
    raw = read_yaml(path) if path else {}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigurationError("Settings must be a YAML mapping")
    env_keys = {
        "PIPELINE_DATABASE_PATH": "database_path",
        "PIPELINE_ARTIFACT_DIR": "artifact_dir",
        "PIPELINE_PROFILE_PATH": "profile_path",
        "PIPELINE_COMPANIES_PATH": "companies_path",
        "PIPELINE_SEARCHES_PATH": "searches_path",
        "RESUME_MATCHER_URL": "resume_matcher_url",
        "LLM_BASE_URL": "llm_base_url",
        "LLM_MODEL": "llm_model",
        "LLM_API_KEY": "llm_api_key",
    }
    for env, key in env_keys.items():
        if value := os.getenv(env):
            raw[key] = value
    if urls := os.getenv("PIPELINE_NOTIFICATION_URLS"):
        try:
            raw["notification_urls"] = json.loads(urls)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("PIPELINE_NOTIFICATION_URLS must be a JSON list") from exc
    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        # Pydantic's normal error text includes inputs, which can contain tokens.
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        raise ConfigurationError(f"Invalid settings fields: {fields}") from exc


def load_profile(path: Path) -> CandidateProfile:
    try:
        profile = CandidateProfile.model_validate(read_yaml(path))
    except ValidationError as exc:
        raise ConfigurationError("Invalid candidate profile; check the example schema") from exc
    ids = [fact.id for fact in profile.facts]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("Candidate fact IDs must be unique")
    return profile


def load_companies(path: Path) -> list[Company]:
    raw = read_yaml(path)
    if not isinstance(raw, list):
        raise ConfigurationError("Company configuration must be a YAML list")
    try:
        companies = [Company.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ConfigurationError("Invalid company; check the example schema") from exc
    if len({company.id for company in companies}) != len(companies):
        raise ConfigurationError("Company IDs must be unique")
    return companies


def load_searches(path: Path | None) -> list[SearchQuery]:
    if path is None:
        return []
    raw = read_yaml(path)
    if not isinstance(raw, list):
        raise ConfigurationError("Search configuration must be a YAML list")
    try:
        searches = [SearchQuery.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ConfigurationError("Invalid search; check the example schema") from exc
    if len({query.id for query in searches}) != len(searches):
        raise ConfigurationError("Search IDs must be unique")
    return searches
