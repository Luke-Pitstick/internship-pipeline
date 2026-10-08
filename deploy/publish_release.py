#!/usr/bin/env python3
"""Validate accepted candidate evidence, then promote its exact OCI bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from typing import Any

from build_release_assets import build_release_assets, clean_source

WORKFLOW = ".github/workflows/container-images.yml"
ARCHES = ("amd64", "arm64")


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def image_config_digest(value: object) -> str:
    """Canonicalize Docker and Podman's full SHA-256 image config identities."""
    if not isinstance(value, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value):
        raise ValueError("Invalid image config digest.")
    return "sha256:" + value.removeprefix("sha256:")


def artifact_file(directory: Path, name: str) -> Path:
    """Actions may preserve a common ancestor; require one regular named file."""
    require(directory.is_dir() and not directory.is_symlink(), "Missing artifact directory.")
    paths = list(directory.rglob("*"))
    require(not any(path.is_symlink() for path in paths), "Artifact contains a symbolic link.")
    matches = [path for path in paths if path.name == name and path.is_file()]
    require(len(matches) == 1, f"Missing or ambiguous artifact file: {name}")
    return matches[0]


def validate_run(
    run: dict[str, Any], *, repository: str, source_commit: str, default_branch: str
) -> None:
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository),
        "Invalid repository.",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit), "Invalid source SHA.")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", default_branch), "Invalid default branch.")
    require(
        run["repository"]["full_name"] == repository
        and run["head_repository"]["full_name"] == repository,
        "Candidate is from another repository.",
    )
    require(run["head_sha"] == source_commit, "Candidate source differs from accepted source.")
    require(
        run["status"] == "completed" and run["conclusion"] == "success",
        "Candidate run must have completed successfully.",
    )
    require(run["path"].split("@", 1)[0] == WORKFLOW, "Unexpected candidate workflow.")
    require(
        run["event"] == "workflow_dispatch" and run["head_branch"] == default_branch,
        "Use a manually accepted candidate from the default branch.",
    )


def validate_artifacts(
    artifacts: list[dict[str, Any]], *, package_version: str, source_commit: str, run_id: int
) -> dict[str, dict[str, Any]]:
    result = {}
    for arch in ARCHES:
        name = f"image-{package_version}-{arch}-{source_commit}"
        matching = [item for item in artifacts if item["name"] == name]
        require(len(matching) == 1, f"Missing or duplicate candidate artifact: {name}")
        item = matching[0]
        require(not item["expired"] and item["size_in_bytes"] > 0, "Artifact is empty or expired.")
        require(
            item.get("workflow_run", {}).get("id") == run_id
            and item["workflow_run"]["head_sha"] == source_commit,
            "Artifact belongs to another candidate run/source.",
        )
        result[arch] = item
    require(
        {item["name"] for item in artifacts if item["name"].startswith("image-")}
        == {item["name"] for item in result.values()},
        "Unexpected platform candidate artifact.",
    )
    return result


def inspect_archive(
    path: Path,
    *,
    arch: str,
    image_id: str,
    source_commit: str,
    package_version: str,
    repository: str,
) -> dict[str, Any]:
    """Read only allowlisted blobs; validate digests and subjects without extraction."""
    with tarfile.open(path) as archive:
        members = {member.name: member for member in archive.getmembers()}
        require(len(members) == len(archive.getmembers()), "Duplicate OCI archive member.")
        for member in members.values():
            require(
                member.isdir() or member.isfile(), "OCI archive contains links or special files."
            )
            require(
                member.name in {"index.json", "oci-layout", "blobs", "blobs/sha256"}
                or re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", member.name),
                "Unexpected OCI archive path.",
            )

        def read_json(name: str) -> dict[str, Any]:
            member = members[name]
            require(member.isfile(), "OCI JSON must be a regular file.")
            stream = archive.extractfile(member)
            require(stream is not None, "Missing OCI JSON.")
            assert stream is not None
            result: dict[str, Any] = json.load(stream)
            return result

        checked: set[str] = set()

        def blob(descriptor: dict[str, Any], *, parse: bool = True) -> dict[str, Any]:
            digest = descriptor["digest"]
            require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest), "Invalid OCI blob digest.")
            name = "blobs/sha256/" + digest[7:]
            member = members[name]
            require(
                member.isfile() and member.size == descriptor["size"], "OCI blob size mismatch."
            )
            if digest not in checked:
                stream = archive.extractfile(member)
                assert stream is not None
                hasher = hashlib.sha256()
                while block := stream.read(1024 * 1024):
                    hasher.update(block)
                require("sha256:" + hasher.hexdigest() == digest, "OCI blob hash mismatch.")
                checked.add(digest)
            return read_json(name) if parse else {}

        root = read_json("index.json")
        require(read_json("oci-layout")["imageLayoutVersion"] == "1.0.0", "Unknown OCI layout.")
        # OCI exporters wrap the runnable index in the layout index.
        require(len(root["manifests"]) == 1, "Expected one named candidate index.")
        descriptor = root["manifests"][0]
        index = blob(descriptor)
        require("manifests" in index, "Candidate must retain its attestation index.")
        platform_descriptors = [
            item for item in index["manifests"] if item.get("platform", {}).get("os") == "linux"
        ]
        require(
            len(platform_descriptors) == 1
            and platform_descriptors[0]["platform"]["architecture"] == arch,
            "Candidate contains an unexpected runnable platform.",
        )
        platform_descriptor = platform_descriptors[0]
        manifest = blob(platform_descriptor)
        require(
            manifest["config"]["digest"] == image_id, "OCI config is not the smoke-tested image."
        )
        config = blob(manifest["config"])
        require(
            config["os"] == "linux" and config["architecture"] == arch,
            "OCI config platform mismatch.",
        )
        labels = config["config"]["Labels"]
        require(
            labels["org.opencontainers.image.revision"] == source_commit
            and labels["org.opencontainers.image.version"] == package_version
            and labels["org.opencontainers.image.source"] == f"https://github.com/{repository}",
            "OCI source/version labels differ from accepted candidate.",
        )
        for layer in manifest["layers"]:
            blob(layer, parse=False)
        predicates: set[str] = set()
        for attestation in index["manifests"]:
            if attestation == platform_descriptor:
                continue
            require(
                attestation.get("platform") == {"architecture": "unknown", "os": "unknown"}
                and attestation.get("annotations", {}).get("vnd.docker.reference.type")
                == "attestation-manifest"
                and attestation["annotations"].get("vnd.docker.reference.digest")
                == platform_descriptor["digest"],
                "Unexpected OCI attestation descriptor.",
            )
            attested_manifest = blob(attestation)
            blob(attested_manifest["config"])
            for layer in attested_manifest["layers"]:
                statement = blob(layer)
                require(
                    any(
                        subject.get("digest", {}).get("sha256") == platform_descriptor["digest"][7:]
                        for subject in statement["subject"]
                    ),
                    "Attestation subject mismatch.",
                )
                predicates.add(statement["predicateType"])
        require(
            "https://spdx.dev/Document" in predicates
            and any(value.startswith("https://slsa.dev/provenance/") for value in predicates),
            "Candidate is missing SBOM or provenance.",
        )
        with path.open("rb") as stream:
            archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {
            "index_digest": descriptor["digest"],
            "manifests": index["manifests"],
            "platform_manifest": platform_descriptor["digest"],
            "config_digest": image_id,
            "archive_sha256": archive_digest,
        }


def validate_candidate(
    source_dir: Path,
    artifacts_dir: Path,
    run: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    repository: str,
    source_commit: str,
    version: str,
    default_branch: str,
) -> dict[str, Any]:
    validate_run(
        run, repository=repository, source_commit=source_commit, default_branch=default_branch
    )
    clean_source(source_dir, source_commit)
    package_version = tomllib.loads((source_dir / "pyproject.toml").read_text())["project"][
        "version"
    ]
    require(
        re.fullmatch(
            r"v" + re.escape(package_version) + r"-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", version
        ),
        "Publication stages explicit prereleases matching the package version.",
    )
    accepted = validate_artifacts(
        artifacts, package_version=package_version, source_commit=source_commit, run_id=run["id"]
    )
    platforms = {}
    for arch, artifact in accepted.items():
        directory = artifacts_dir / artifact["name"]
        archive_path = artifact_file(directory, f"pipeline-{arch}.tar")
        require(
            artifact_file(directory, "source-revision.txt").read_text().strip() == source_commit,
            "Artifact source revision mismatch.",
        )
        for name in ("pyproject.toml", "uv.lock", "web/package-lock.json"):
            require(
                artifact_file(directory, Path(name).name).read_bytes()
                == (source_dir / name).read_bytes(),
                "Artifact dependency lock mismatch.",
            )
        checksum = artifact_file(directory, f"oci-{arch}.sha256").read_text().split()
        with archive_path.open("rb") as stream:
            require(
                len(checksum) == 2
                and checksum[0] == hashlib.file_digest(stream, "sha256").hexdigest()
                and checksum[1] == f"/tmp/pipeline-{arch}.tar",
                "OCI archive checksum mismatch.",
            )
        reports = [
            json.loads(artifact_file(directory, f"{engine}-{arch}.json").read_text())
            for engine in ("docker", "podman")
        ]
        expected_digest = image_config_digest(reports[0]["image_id"])
        for engine, report in zip(("docker", "podman"), reports, strict=True):
            require(
                report["engine"] == engine
                and report["image_platform"] == f"linux/{arch}"
                and image_config_digest(report["image_id"]) == expected_digest,
                "Smoke-tested platform/image mismatch.",
            )
        platforms[arch] = inspect_archive(
            archive_path,
            arch=arch,
            image_id=expected_digest,
            source_commit=source_commit,
            package_version=package_version,
            repository=repository,
        ) | {
            "artifact_id": artifact["id"],
            "artifact_name": artifact["name"],
            "smoke_reports": reports,
        }
    return {
        "repository": repository,
        "source_commit": source_commit,
        "version": version,
        "run_id": run["id"],
        "run_url": run["html_url"],
        "platforms": platforms,
    }


def command(*args: str) -> bytes:
    return subprocess.check_output(args)


def promote(
    candidate: dict[str, Any], artifacts_dir: Path, source_dir: Path, output_dir: Path
) -> None:
    """Call established tools only after validation; never rebuild or replace identities."""
    repository, version = candidate["repository"], candidate["version"]
    image = "ghcr.io/" + repository.lower()
    require(
        not output_dir.exists() and not output_dir.is_symlink(), "Release output already exists."
    )
    # The workflow concurrency group serializes releases for this repository.
    for tag in (version, version + "-amd64", version + "-arm64"):
        probe = subprocess.run(
            ["skopeo", "inspect", "--raw", f"docker://{image}:{tag}"],
            capture_output=True,
            check=False,
        )
        require(
            probe.returncode != 0
            and not any(
                message in probe.stderr.lower()
                for message in (b"unauthorized", b"denied", b"authentication required")
            )
            and (
                any(code in probe.stderr for code in (b"MANIFEST_UNKNOWN", b"NAME_UNKNOWN"))
                or any(
                    message in probe.stderr.lower()
                    for message in (b"manifest unknown", b"name unknown")
                )
            ),
            f"Refusing existing tag or inconclusive registry check: {tag}",
        )
    release = command("gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases")
    require(
        all(item["tag_name"] != version for page in json.loads(release) for item in page),
        "Release already exists.",
    )
    tag = subprocess.run(
        ["gh", "api", f"repos/{repository}/git/ref/tags/{version}"],
        capture_output=True,
        check=False,
    )
    require(
        tag.returncode != 0 and b"HTTP 404" in tag.stderr,
        "Refusing existing Git tag or inconclusive tag lookup.",
    )
    source_indexes = {}
    for arch in ARCHES:
        platform = candidate["platforms"][arch]
        archive = artifact_file(artifacts_dir / platform["artifact_name"], f"pipeline-{arch}.tar")
        raw = command("skopeo", "inspect", "--raw", f"oci-archive:{archive}")
        require(
            "sha256:" + hashlib.sha256(raw).hexdigest() == platform["index_digest"],
            "Skopeo selected a different candidate index.",
        )
        source_indexes[arch] = raw
    state_path = output_dir.parent / "release-publication-state.json"
    require(not state_path.exists() and not state_path.is_symlink(), "Publication evidence exists.")
    state: dict[str, Any] = {
        "source_commit": candidate["source_commit"],
        "version": version,
        "operations": [],
    }

    def record(destination: str, status: str, digest: str | None = None) -> None:
        state["operations"].append({"destination": destination, "status": status, "digest": digest})
        state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")

    refs = []
    for arch in ARCHES:
        platform = candidate["platforms"][arch]
        archive = artifact_file(artifacts_dir / platform["artifact_name"], f"pipeline-{arch}.tar")
        source_raw = source_indexes[arch]
        destination = f"docker://{image}:{version}-{arch}"
        record(destination, "attempting", platform["index_digest"])
        command(
            "skopeo",
            "copy",
            "--all",
            "--preserve-digests",
            f"oci-archive:{archive}",
            destination,
        )
        registry_raw = command("skopeo", "inspect", "--raw", f"docker://{image}:{version}-{arch}")
        require(source_raw == registry_raw, "Registry changed candidate index bytes.")
        record(destination, "verified", platform["index_digest"])
        refs.append(f"{image}@{platform['index_digest']}")
    record(f"{image}:{version}", "attempting")
    command("docker", "buildx", "imagetools", "create", "--tag", f"{image}:{version}", *refs)
    combined = command("skopeo", "inspect", "--raw", f"docker://{image}:{version}")
    expected = [
        descriptor for arch in ARCHES for descriptor in candidate["platforms"][arch]["manifests"]
    ]
    actual = json.loads(combined)["manifests"]
    require(
        sorted(actual, key=lambda item: item["digest"])
        == sorted(expected, key=lambda item: item["digest"]),
        "Combined index changed or dropped platform/attestation descriptors.",
    )
    pinned = image + "@sha256:" + hashlib.sha256(combined).hexdigest()
    record(f"{image}:{version}", "verified", pinned.split("@", 1)[1])
    build_release_assets(
        source_dir,
        output_dir,
        repository=repository,
        version=version,
        source_commit=candidate["source_commit"],
        image=pinned,
        candidate=candidate,
    )
    notes = output_dir.parent / "release-notes.md"
    notes.write_text(
        f"Accepted candidate: {candidate['run_url']}\nSource: {candidate['source_commit']}\n"
        f"Image: {pinned}\n\n"
        "Draft prerelease; public download and host acceptance remain separate.\n"
        f"After publication: curl -fsSL https://github.com/{repository}"
        f"/releases/download/{version}/install.sh | sh\n"
    )
    record(f"https://github.com/{repository}/releases/tag/{version}", "attempting")
    command(
        "gh",
        "release",
        "create",
        version,
        "--repo",
        repository,
        "--target",
        candidate["source_commit"],
        "--draft",
        "--prerelease",
        "--latest=false",
        "--title",
        f"Internship Pipeline {version}",
        "--notes-file",
        str(notes),
        *(str(path) for path in sorted(output_dir.iterdir())),
    )
    record(f"https://github.com/{repository}/releases/tag/{version}", "draft-created")


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    cli.add_argument("--source-dir", type=Path, required=True)
    cli.add_argument("--artifacts-dir", type=Path, required=True)
    cli.add_argument("--run-json", type=Path, required=True)
    cli.add_argument("--artifacts-json", type=Path, required=True)
    cli.add_argument("--repository", required=True)
    cli.add_argument("--default-branch", required=True)
    cli.add_argument("--source-commit", required=True)
    cli.add_argument("--version", required=True)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument(
        "--promote", action="store_true", help="Write GHCR tags and a draft prerelease"
    )
    args = cli.parse_args()
    try:
        pages = json.loads(args.artifacts_json.read_text())
        artifacts = [item for page in pages for item in page["artifacts"]]
        candidate = validate_candidate(
            args.source_dir,
            args.artifacts_dir,
            json.loads(args.run_json.read_text()),
            artifacts,
            repository=args.repository,
            source_commit=args.source_commit,
            version=args.version,
            default_branch=args.default_branch,
        )
        require(
            not args.output_dir.exists() and not args.output_dir.is_symlink(),
            "Release output already exists.",
        )
        # Validate generated shell/bundle before the first registry write.
        preview = args.output_dir.with_name(args.output_dir.name + "-preview")
        build_release_assets(
            args.source_dir,
            preview,
            repository=args.repository,
            version=args.version,
            source_commit=args.source_commit,
            image=f"ghcr.io/{args.repository.lower()}@sha256:" + "0" * 64,
            candidate=candidate,
        )
        subprocess.run(["sh", "-n", str(preview / "install.sh")], check=True)
        if args.promote:
            promote(candidate, args.artifacts_dir, args.source_dir, args.output_dir)
        print(json.dumps(candidate, sort_keys=True, indent=2))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as exc:
        print(
            f"Publication failed: {exc}. Inspect partial registry/release writes before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
