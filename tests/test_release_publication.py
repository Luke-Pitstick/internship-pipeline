"""Publication refuses mismatched evidence before any remote mutation."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import publish_release as publication  # noqa: E402
from test_release_assets import REPOSITORY, VERSION, source_repository  # noqa: E402


def make_oci(path: Path, arch: str, revision: str) -> tuple[str, bytes]:
    blobs: dict[str, bytes] = {}

    def blob(value: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(payload).hexdigest()
        blobs["blobs/sha256/" + digest] = payload
        return {
            "digest": "sha256:" + digest,
            "size": len(payload),
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
        }

    config = blob(
        {
            "os": "linux",
            "architecture": arch,
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": revision,
                    "org.opencontainers.image.version": "0.1.0",
                    "org.opencontainers.image.source": f"https://github.com/{REPOSITORY}",
                }
            },
        }
    )
    manifest = blob({"config": config, "layers": [blob({"synthetic": "layer"})]})
    manifest["platform"] = {"os": "linux", "architecture": arch}
    layers = []
    for predicate in ("https://spdx.dev/Document", "https://slsa.dev/provenance/v0.2"):
        layers.append(
            blob(
                {
                    "predicateType": predicate,
                    "predicate": {},
                    "subject": [{"digest": {"sha256": manifest["digest"][7:]}}],
                }
            )
        )
    attestation = blob({"config": blob({}), "layers": layers})
    attestation["platform"] = {"os": "unknown", "architecture": "unknown"}
    attestation["annotations"] = {
        "vnd.docker.reference.type": "attestation-manifest",
        "vnd.docker.reference.digest": manifest["digest"],
    }
    index = {"manifests": [manifest, attestation]}
    root = blob(index)
    blobs["index.json"] = json.dumps({"manifests": [root]}).encode()
    blobs["oci-layout"] = b'{"imageLayoutVersion":"1.0.0"}'
    with tarfile.open(path, "w") as archive:
        for name, payload in blobs.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return config["digest"], json.dumps(index, sort_keys=True).encode()


def candidate_fixture(
    tmp_path: Path,
) -> tuple[Path, str, Path, dict[str, Any], list[dict[str, Any]]]:
    source, revision = source_repository(tmp_path / "source")
    artifacts_dir = tmp_path / "artifacts"
    artifacts = []
    for arch in publication.ARCHES:
        name = f"image-0.1.0-{arch}-{revision}"
        root = artifacts_dir / name
        # Reproduce upload-artifact's mixed absolute/relative common-ancestor layout.
        directory = root / "home/runner/work/pipeline/pipeline/evidence"
        directory.mkdir(parents=True)
        archive = root / "tmp" / f"pipeline-{arch}.tar"
        archive.parent.mkdir()
        image_id, _ = make_oci(archive, arch, revision)
        (directory / "source-revision.txt").write_text(revision + "\n")
        for filename in ("pyproject.toml", "uv.lock", "web/package-lock.json"):
            (directory / Path(filename).name).write_bytes((source / filename).read_bytes())
        for engine in ("docker", "podman"):
            (directory / f"{engine}-{arch}.json").write_text(
                json.dumps(
                    {"engine": engine, "image_id": image_id, "image_platform": f"linux/{arch}"}
                )
            )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (directory / f"oci-{arch}.sha256").write_text(f"{digest}  /tmp/pipeline-{arch}.tar\n")
        artifacts.append(
            {
                "id": len(artifacts) + 1,
                "name": name,
                "expired": False,
                "size_in_bytes": archive.stat().st_size,
                "workflow_run": {"id": 10, "head_sha": revision},
            }
        )
    run = {
        "id": 10,
        "html_url": f"https://github.com/{REPOSITORY}/actions/runs/10",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "head_sha": revision,
        "head_branch": "main",
        "path": publication.WORKFLOW,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
    }
    return source, revision, artifacts_dir, run, artifacts


def validate(fixture: tuple[Any, ...]) -> dict[str, Any]:
    source, revision, directory, run, artifacts = fixture
    return publication.validate_candidate(
        source,
        directory,
        run,
        artifacts,
        repository=REPOSITORY,
        source_commit=revision,
        version=VERSION,
        default_branch="main",
    )


def test_nested_candidate_archives_bind_tested_configs_and_attestations(tmp_path: Path) -> None:
    candidate = validate(candidate_fixture(tmp_path))
    assert set(candidate["platforms"]) == {"amd64", "arm64"}
    for platform in candidate["platforms"].values():
        assert len(platform["manifests"]) == 2
        assert platform["config_digest"] == platform["smoke_reports"][0]["image_id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("conclusion", "failure"),
        ("head_sha", "a" * 40),
        ("event", "pull_request"),
        ("head_branch", "feature"),
        ("path", ".github/workflows/untrusted.yml"),
    ],
)
def test_wrong_candidate_runs_are_rejected(tmp_path: Path, field: str, value: str) -> None:
    fixture = candidate_fixture(tmp_path)
    fixture[3][field] = value
    with pytest.raises(ValueError):
        validate(fixture)


def test_fork_and_ambiguous_artifact_are_rejected(tmp_path: Path) -> None:
    fixture = candidate_fixture(tmp_path)
    fixture[3]["head_repository"]["full_name"] = "another/pipeline"
    with pytest.raises(ValueError, match="another repository"):
        validate(fixture)
    fixture[3]["head_repository"]["full_name"] = REPOSITORY
    fixture[4].append(copy.deepcopy(fixture[4][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate(fixture)


@pytest.mark.parametrize("failure", ["checksum", "source", "config", "lock", "duplicate", "link"])
def test_evidence_mismatch_and_ambiguous_files_are_rejected(tmp_path: Path, failure: str) -> None:
    fixture = candidate_fixture(tmp_path)
    directory = fixture[2] / fixture[4][0]["name"]
    if failure == "checksum":
        publication.artifact_file(directory, "pipeline-amd64.tar").write_bytes(b"corrupt")
    elif failure == "source":
        publication.artifact_file(directory, "source-revision.txt").write_text("a" * 40)
    elif failure == "config":
        report = publication.artifact_file(directory, "podman-amd64.json")
        data = json.loads(report.read_text())
        data["image_id"] = "sha256:" + "a" * 64
        report.write_text(json.dumps(data))
    elif failure == "lock":
        publication.artifact_file(directory, "uv.lock").write_text("different")
    elif failure == "duplicate":
        (directory / "source-revision.txt").write_text(fixture[1])
    else:
        (directory / "symbolic").symlink_to("/tmp")
    with pytest.raises(ValueError):
        validate(fixture)


def test_archive_blob_tampering_is_rejected(tmp_path: Path) -> None:
    fixture = candidate_fixture(tmp_path)
    path = publication.artifact_file(fixture[2] / fixture[4][0]["name"], "pipeline-amd64.tar")
    payload = path.read_bytes().replace(b'"0.1.0"', b'"9.9.9"')
    path.write_bytes(payload)
    checksum = publication.artifact_file(fixture[2] / fixture[4][0]["name"], "oci-amd64.sha256")
    checksum.write_text(hashlib.sha256(payload).hexdigest() + "  /tmp/pipeline-amd64.tar\n")
    with pytest.raises(ValueError, match="blob hash"):
        validate(fixture)


def test_dry_run_validates_full_assets_without_remote_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, revision, directory, run, artifacts = candidate_fixture(tmp_path)
    run_path, artifact_path = tmp_path / "run.json", tmp_path / "artifacts.json"
    run_path.write_text(json.dumps(run))
    artifact_path.write_text(json.dumps([{"artifacts": artifacts}]))
    monkeypatch.setattr(publication, "command", lambda *args: pytest.fail("Unexpected remote call"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_release.py",
            "--source-dir",
            str(source),
            "--artifacts-dir",
            str(directory),
            "--run-json",
            str(run_path),
            "--artifacts-json",
            str(artifact_path),
            "--repository",
            REPOSITORY,
            "--default-branch",
            "main",
            "--source-commit",
            revision,
            "--version",
            VERSION,
            "--output-dir",
            str(tmp_path / "release"),
        ],
    )
    assert publication.main() == 0
    assert (tmp_path / "release-preview/install.sh").is_file()
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("missing_code", [b"MANIFEST_UNKNOWN", b"NAME_UNKNOWN"])
def test_promote_passes_literal_argv_preserves_digests_and_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_code: bytes
) -> None:
    source, revision, directory, run, artifacts = candidate_fixture(tmp_path)
    candidate = validate((source, revision, directory, run, artifacts))
    commands = []
    indexes = {}
    for arch in publication.ARCHES:
        archive = publication.artifact_file(
            directory / artifacts[publication.ARCHES.index(arch)]["name"], f"pipeline-{arch}.tar"
        )
        with tarfile.open(archive) as tar:
            entry = tar.extractfile(
                "blobs/sha256/" + candidate["platforms"][arch]["index_digest"][7:]
            )
            assert entry is not None
            indexes[arch] = entry.read()
    combined = json.dumps(
        {
            "manifests": [
                item
                for arch in publication.ARCHES
                for item in candidate["platforms"][arch]["manifests"]
            ]
        }
    ).encode()

    def fake_command(*args: str) -> bytes:
        commands.append(args)
        if args[:2] == ("gh", "api"):
            return b"[[]]"
        if args[:3] == ("skopeo", "inspect", "--raw"):
            for arch in publication.ARCHES:
                if args[-1].endswith((f"pipeline-{arch}.tar", f"{VERSION}-{arch}")):
                    return indexes[arch]
            return combined
        return b""

    def absent(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, b"", missing_code + b" HTTP 404")

    monkeypatch.setattr(publication, "command", fake_command)
    monkeypatch.setattr(publication.subprocess, "run", absent)
    # build_release_assets clean_source uses check_output, which shares subprocess.run internally.
    monkeypatch.setattr(
        publication,
        "build_release_assets",
        lambda *args, **kwargs: (args[1].mkdir(), (args[1] / "install.sh").write_text("synthetic")),
    )
    publication.promote(candidate, directory, source, tmp_path / "release with spaces")
    copies = [args for args in commands if args[:2] == ("skopeo", "copy")]
    assert len(copies) == 2 and all(args[2:4] == ("--all", "--preserve-digests") for args in copies)
    buildx = next(
        args for args in commands if args[:4] == ("docker", "buildx", "imagetools", "create")
    )
    assert all("@sha256:" in arg for arg in buildx[6:])
    release = next(args for args in commands if args[:3] == ("gh", "release", "create"))
    assert "--draft" in release and "--prerelease" in release and "--latest=false" in release
    assert release[release.index("--target") + 1] == revision
    assert str(tmp_path / "release with spaces/install.sh") in release
    state = json.loads((tmp_path / "release-publication-state.json").read_text())
    assert state["operations"][-1]["status"] == "draft-created"


@pytest.mark.parametrize("failure", ["registry-exists", "denied", "network", "git-tag", "release"])
def test_preflight_refuses_existing_identities_and_inconclusive_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = candidate_fixture(tmp_path)
    source, _, directory, _, _ = fixture
    candidate = validate(fixture)
    commands = []

    def probe(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "gh":
            return subprocess.CompletedProcess(
                args, 0 if failure == "git-tag" else 1, b"", b"HTTP 404"
            )
        if failure == "registry-exists":
            return subprocess.CompletedProcess(args, 0, b"{}", b"")
        message = {"denied": b"DENIED", "network": b"connection timed out"}.get(
            failure, b"MANIFEST_UNKNOWN"
        )
        return subprocess.CompletedProcess(args, 1, b"", message)

    def readonly(*args: str) -> bytes:
        commands.append(args)
        assert args[:2] == ("gh", "api"), "Remote mutation before preflight rejection"
        return json.dumps([[{"tag_name": VERSION}]] if failure == "release" else [[]]).encode()

    monkeypatch.setattr(publication.subprocess, "run", probe)
    monkeypatch.setattr(publication, "command", readonly)
    with pytest.raises(ValueError):
        publication.promote(candidate, directory, source, tmp_path / "release")
    assert not (tmp_path / "release-publication-state.json").exists()
