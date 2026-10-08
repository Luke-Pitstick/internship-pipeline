"""Executable installer artifact checks using synthetic bytes and HTTPS responses."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import urllib.error
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
VERSION = "v0.1.0-rc.1"
STEM = f"internship-pipeline-installer-{VERSION}"
URL = f"https://downloads.invalid/releases/{VERSION}/{STEM}.tar.gz"
IMAGE = "ghcr.io/example/pipeline@sha256:" + "b" * 64


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("build_installer_bundle")
bootstrap = load("bootstrap_installer")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source"
    path.mkdir()
    for filename in builder.BUNDLE_FILES:
        (path / filename).write_text(f"# Synthetic installer file: {filename}\n")
    (path.parent / "LICENSE").write_text("Synthetic project license notice\n")
    (path / "private-token.env").write_text("synthetic-private-sentinel")
    (path / "session-output.json").write_text("synthetic-session-sentinel")
    return path


def make_bundle(source: Path, output: Path) -> tuple[bytes, dict[str, object]]:
    metadata = builder.build_bundle(source, output, VERSION, "a" * 40)
    return (output / str(metadata["archive"])).read_bytes(), metadata


def make_tar(members: list[tarfile.TarInfo], data: bytes = b"synthetic\n") -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for member in members:
            if member.isfile():
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            else:
                archive.addfile(member)
    return gzip.compress(stream.getvalue(), mtime=0)


def complete_members() -> list[tarfile.TarInfo]:
    return [tarfile.TarInfo(f"{STEM}/{name}") for name in builder.ARCHIVE_FILES]


def response_for(payload: bytes, *, length: str | None = None, status: int = 200) -> Mock:
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = status
    response.headers = {} if length is None else {"Content-Length": length}
    response.geturl.return_value = URL
    response.read1.side_effect = [payload, b""]
    return response


def mock_response(monkeypatch: pytest.MonkeyPatch, response: Mock) -> Mock:
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", Mock(return_value=opener))
    return opener


def test_bundle_is_deterministic_and_contains_exact_current_files(
    source: Path, tmp_path: Path
) -> None:
    first, metadata = make_bundle(source, tmp_path / "one")
    for path in source.iterdir():
        os.utime(path, (12345, 12345))
        path.chmod(0o777)
    second, second_metadata = make_bundle(source, tmp_path / "two")
    assert first == second
    assert metadata == second_metadata
    assert metadata["archive_sha256"] == hashlib.sha256(first).hexdigest()
    assert first[4:8] == b"\0" * 4  # gzip timestamp
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:gz") as archive:
        assert archive.getnames() == [f"{STEM}/{name}" for name in builder.ARCHIVE_FILES]
        for member in archive:
            assert member.mtime == member.uid == member.gid == 0
            assert member.uname == member.gname == ""
            stream = archive.extractfile(member)
            assert stream is not None
            name = Path(member.name).name
            original = source.parent / name if name == "LICENSE" else source / name
            assert stream.read() == original.read_bytes()
    serialized = json.loads((tmp_path / "one" / f"{STEM}.json").read_text())
    assert serialized == metadata
    assert (tmp_path / "one" / f"{STEM}.tar.gz.sha256").read_text() == (
        f"{metadata['archive_sha256']}  {STEM}.tar.gz\n"
    )
    assert "private-token" not in str(metadata)
    (source / "install.py").write_text("# changed final bytes\n")
    changed, _ = make_bundle(source, tmp_path / "three")
    assert changed != first


@pytest.mark.parametrize("kind", ["missing", "symlink", "empty", "oversize"])
def test_builder_rejects_incomplete_or_unsafe_source(
    kind: str, source: Path, tmp_path: Path
) -> None:
    target = source / "install.py"
    target.unlink()
    if kind == "symlink":
        target.symlink_to(source / "install.sh")
    elif kind == "empty":
        target.touch()
    elif kind == "oversize":
        target.write_bytes(b"x" * (builder.MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError):
        make_bundle(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("version", ["latest", "v1", "v0.1.0/../private", "v0.1.0\n"])
def test_builder_requires_safe_release_version(version: str, source: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        builder.build_bundle(source, tmp_path / "out", version, "a" * 40)


def test_builder_does_not_overwrite_candidate(source: Path, tmp_path: Path) -> None:
    first, _ = make_bundle(source, tmp_path / "out")
    with pytest.raises(ValueError, match="already exists"):
        make_bundle(source, tmp_path / "out")
    assert (tmp_path / "out" / f"{STEM}.tar.gz").read_bytes() == first


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_builder_requires_root_license_notice(kind: str, source: Path, tmp_path: Path) -> None:
    notice = source.parent / "LICENSE"
    notice.unlink()
    if kind == "symlink":
        notice.symlink_to(source / "install.sh")
    with pytest.raises(ValueError, match="LICENSE"):
        make_bundle(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_builder_refuses_an_archive_too_large_for_bootstrap(
    source: Path, tmp_path: Path
) -> None:
    for name in builder.BUNDLE_FILES:
        (source / name).write_bytes(os.urandom(512 * 1024))
    with pytest.raises(ValueError, match="bootstrap download size"):
        make_bundle(source, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_unpack_round_trip(source: Path, tmp_path: Path) -> None:
    payload, _ = make_bundle(source, tmp_path / "out")
    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    bundle = bootstrap.unpack(payload, destination, VERSION)
    assert sorted(path.name for path in bundle.iterdir()) == sorted(builder.ARCHIVE_FILES)
    for name in builder.ARCHIVE_FILES:
        target = bundle / name
        original = source.parent / name if name == "LICENSE" else source / name
        assert target.read_bytes() == original.read_bytes()
        assert target.stat().st_mode & 0o777 == (
            0o700 if name in {"install.sh", "internship-pipeline"} else 0o600
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        "traversal",
        "absolute",
        "symlink",
        "hardlink",
        "device",
        "duplicate",
        "extra",
        "missing",
        "pax",
        "wrong_version",
    ],
)
def test_unpack_rejects_entire_bad_archive_before_writing(unsafe: str, tmp_path: Path) -> None:
    members = complete_members()
    if unsafe == "traversal":
        members[0].name = f"{STEM}/../escape"
    elif unsafe == "absolute":
        members[0].name = "/tmp/escape"
    elif unsafe == "symlink":
        members[0].type = tarfile.SYMTYPE
        members[0].linkname = "../escape"
    elif unsafe == "hardlink":
        members[0].type = tarfile.LNKTYPE
        members[0].linkname = f"{STEM}/install.py"
    elif unsafe == "device":
        members[0].type = tarfile.CHRTYPE
    elif unsafe == "duplicate":
        members.append(tarfile.TarInfo(members[0].name))
    elif unsafe == "extra":
        members.append(tarfile.TarInfo(f"{STEM}/credentials.env"))
    elif unsafe == "missing":
        members.pop()
    elif unsafe == "pax":
        members[0].pax_headers = {"comment": "unexpected metadata"}
    elif unsafe == "wrong_version":
        members[0].name = "internship-pipeline-installer-v0.0.0/install.sh"
    with pytest.raises(ValueError):
        bootstrap.unpack(make_tar(members), tmp_path, VERSION)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mutation", ["truncated", "gzip_crc", "bad_tar"])
def test_unpack_rejects_corruption(mutation: str, source: Path, tmp_path: Path) -> None:
    payload, _ = make_bundle(source, tmp_path / "out")
    if mutation == "truncated":
        payload = payload[:-10]
    elif mutation == "gzip_crc":
        payload = payload[:-8] + bytes([payload[-8] ^ 1]) + payload[-7:]
    else:
        payload = gzip.compress(b"invalid tar")
    destination = tmp_path / "private"
    destination.mkdir()
    with pytest.raises((EOFError, OSError, tarfile.TarError, ValueError)):
        bootstrap.unpack(payload, destination, VERSION)
    assert list(destination.iterdir()) == []


def test_unpack_bounds_expansion(tmp_path: Path) -> None:
    payload = gzip.compress(b"0" * (bootstrap.MAX_TAR_BYTES + 1))
    with pytest.raises(ValueError, match="expands"):
        bootstrap.unpack(payload, tmp_path, VERSION)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("size", [0, bootstrap.MAX_FILE_BYTES + 1])
def test_unpack_rejects_invalid_individual_file_size(size: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        bootstrap.unpack(make_tar(complete_members(), b"x" * size), tmp_path, VERSION)
    assert list(tmp_path.iterdir()) == []


def test_download_validates_tls_size_and_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"reviewed archive bytes"
    response = response_for(payload, length=str(len(payload)))
    opener = mock_response(monkeypatch, response)
    assert bootstrap.download(URL, hashlib.sha256(payload).hexdigest()) == payload
    request = opener.open.call_args.args[0]
    assert request.full_url == URL
    assert request.get_header("Accept-encoding") == "identity"
    assert opener.open.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize(
    "problem",
    [
        "truncated",
        "hash",
        "empty",
        "oversize",
        "invalid_length",
        "http_status",
        "downgrade",
        "deadline",
        "read_failure",
    ],
)
def test_download_rejects_failures(problem: str, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"archive bytes"
    response = response_for(payload)
    if problem == "truncated":
        response.headers = {"Content-Length": str(len(payload) + 1)}
    elif problem == "empty":
        response.read1.side_effect = [b""]
    elif problem == "oversize":
        response.read1.side_effect = [b"x" * (bootstrap.MAX_DOWNLOAD_BYTES + 1)]
    elif problem == "invalid_length":
        response.headers = {"Content-Length": "not-an-integer"}
    elif problem == "http_status":
        response.status = 206
    elif problem == "downgrade":
        response.geturl.return_value = URL.replace("https:", "http:")
    elif problem == "deadline":
        monkeypatch.setattr(bootstrap.time, "monotonic", Mock(side_effect=[0, 121]))
    elif problem == "read_failure":
        response.read1.side_effect = OSError("network failed")
    mock_response(monkeypatch, response)
    expected = "a" * 64 if problem == "hash" else hashlib.sha256(payload).hexdigest()
    with pytest.raises((ValueError, OSError)):
        bootstrap.download(URL, expected)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/x",
        "file:///tmp/x",
        "https://user:password@example.invalid/x",
        "https://example.invalid/x#fragment",
    ],
)
def test_rejects_unsafe_download_url_without_network(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = Mock()
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", opener)
    with pytest.raises(ValueError):
        bootstrap.download(url, "a" * 64)
    opener.assert_not_called()


def test_redirect_rejects_https_downgrade() -> None:
    request = bootstrap.urllib.request.Request(URL)
    with pytest.raises(ValueError, match="HTTPS"):
        bootstrap.HTTPSRedirects().redirect_request(
            request, None, 302, "Found", {}, "http://example.invalid/archive"
        )


def bootstrap_args() -> list[str]:
    return ["--bundle-url", URL, "--version", VERSION, "--sha256", "a" * 64, "--image", IMAGE]


def test_bootstrap_launches_only_after_verification_and_removes_temp_bundle(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This crosses the actual shell/Python launcher boundary, with synthetic install.py only.
    (source / "install.sh").write_text((DEPLOY / "install.sh").read_text())
    (source / "install.py").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n"
    )
    payload, _ = make_bundle(source, tmp_path / "out")
    download = Mock(return_value=payload)
    monkeypatch.setattr(bootstrap, "download", download)
    actual_run = subprocess.run
    calls: list[list[str]] = []

    def launch(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        result = actual_run(argv, check=check, capture_output=True, text=True)
        assert json.loads(result.stdout) == ["--port", "9191", "--image", IMAGE]
        assert result.stderr == ""
        return result

    monkeypatch.setattr(bootstrap.subprocess, "run", launch)
    assert bootstrap.main([*bootstrap_args(), "--", "--port", "9191"]) == 7
    download.assert_called_once_with(URL, "a" * 64)
    assert not Path(calls[0][1]).exists()


@pytest.mark.parametrize("override", ["--image", "--image=other", "--im", "--imag=other"])
def test_bootstrap_refuses_image_override_without_download(
    override: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = Mock()
    monkeypatch.setattr(bootstrap, "download", download)
    assert bootstrap.main([*bootstrap_args(), "--", override]) == 1
    download.assert_not_called()


def test_bootstrap_never_launches_after_failed_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "download", Mock(side_effect=ValueError("digest mismatch")))
    run = Mock()
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(bootstrap_args()) == 1
    run.assert_not_called()


def test_bootstrap_never_launches_after_bad_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "download", Mock(return_value=make_tar(complete_members()[:-1])))
    run = Mock()
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(bootstrap_args()) == 1
    run.assert_not_called()


def test_bootstrap_download_connection_failure_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = Mock()
    opener.open.side_effect = urllib.error.URLError("synthetic connection failure")
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", Mock(return_value=opener))
    run = Mock()
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(bootstrap_args()) == 1
    run.assert_not_called()


def test_bootstrap_restoration_preserves_local_image_contract(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _ = make_bundle(source, tmp_path / "out")
    monkeypatch.setattr(bootstrap, "download", Mock(return_value=payload))
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    args = bootstrap_args()[:-2]
    forwarded = ["--restore-source=/private/source", "--restore-from", "/private/backup"]
    assert bootstrap.main([*args, "--", *forwarded]) == 0
    assert run.call_args.args[0][2:] == forwarded
    assert bootstrap.main([*args, "--", "--restore-source=/private/source"]) == 1
    assert bootstrap.main([*bootstrap_args(), "--", *forwarded]) == 1


@pytest.mark.parametrize("change", ["version", "image_tag"])
def test_bootstrap_requires_reviewed_version_and_digest(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = bootstrap_args()
    if change == "version":
        args[3] = "v0.0.0"
    elif change == "image_tag":
        args[-1] = "ghcr.io/example/pipeline:v0.1.0"
    download = Mock()
    monkeypatch.setattr(bootstrap, "download", download)
    assert bootstrap.main(args) == 1
    download.assert_not_called()


def test_bootstrap_saved_manifest_rerun_has_no_image_override(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _ = make_bundle(source, tmp_path / "out")
    monkeypatch.setattr(bootstrap, "download", Mock(return_value=payload))
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    args = bootstrap_args()[:-2]
    assert bootstrap.main([*args, "--", "--install-dir", "/private/saved-root"]) == 0
    assert run.call_args.args[0][2:] == ["--install-dir", "/private/saved-root"]
