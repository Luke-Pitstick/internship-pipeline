"""Conservative URL identity and material posting revision normalization."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from internship_pipeline.models import SourceJob

_TRACKING_KEYS = {"gclid", "fbclid", "msclkid", "gh_src", "lever-source", "lever-origin"}


def canonical_url(url: str) -> str:
    """Return opportunity identity, preserving generic job routing semantics.

    Keep query order, repeated parameters, blank values, escaping, path case,
    trailing slashes and fragments: any of these can identify a requisition.
    Only known Lever/Ashby application endpoints normalize to their listing.
    Keep the original application URL on SourceJob for delivery.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Job URL must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Job URL must not contain credentials")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    scheme = parts.scheme.lower()
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    query = "&".join(
        component
        for component in parts.query.split("&")
        if not _is_tracking(component.partition("=")[0])
    )
    path = parts.path
    segments = path.split("/")
    endpoint = {
        "jobs.lever.co": "apply",
        "jobs.eu.lever.co": "apply",
        "jobs.ashbyhq.com": "application",
    }.get(parts.hostname.lower())
    if endpoint and len(segments) == 4 and all(segments[1:]) and segments[-1] == endpoint:
        path = "/".join(segments[:-1])
    return urlunsplit((scheme, host, path, query, parts.fragment))


def _is_tracking(key: str) -> bool:
    key = unquote_plus(key).lower()
    return key.startswith("utm_") or key in _TRACKING_KEYS


def content_hash(posting: SourceJob) -> str:
    """Hash actionable content, independently of source and observation clocks."""
    material = {
        "title": posting.title.strip(),
        "company": posting.company.strip(),
        "apply_url": canonical_url(posting.apply_url),
        "description": posting.description.replace("\r\n", "\n").strip(),
        "locations": sorted(set(location.strip() for location in posting.locations)),
        "employment_type": posting.employment_type,
        "compensation": posting.compensation,
        "deadline": posting.deadline,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
