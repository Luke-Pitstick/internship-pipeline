"""OS isolation and resource limits for owner-supplied TeX; fail closed if unavailable."""

from __future__ import annotations

import json
import os
import resource
import shutil
import sys
from pathlib import Path


def command(executable: str, root: Path, flags: list[str]) -> list[str]:
    engine = shutil.which(executable)
    if not engine:
        raise ValueError("LaTeX compiler unavailable")
    root = root.resolve()
    if sys.platform == "darwin":
        # Exclude home, app state, credentials and network. Only system TeX/fonts are readable.
        reads = ["/System", "/usr", "/bin", "/Library/TeX", "/Library/Fonts", "/private/etc"]
        profile = (
            "(version 1)(deny default)(allow process*)(allow sysctl-read)"
            '(allow file-read-metadata)(allow file-read* (literal "/") (literal "/dev/null")'
            ' (literal "/dev/urandom")'
            + "".join(f" (subpath {json.dumps(p)})" for p in [*reads, str(root)])
            + ")(allow file-write* (subpath "
            + json.dumps(str(root))
            + "))"
        )
        args = ["/usr/bin/sandbox-exec", "-p", profile, engine, *flags]
    elif sys.platform == "linux":
        args = [engine, *flags]
    else:
        raise ValueError("Isolated TeX rendering is supported on Linux and macOS")
    return [sys.executable, "-I", str(Path(__file__).resolve()), *args]


def restrict_linux(root: Path, engine: str) -> None:
    from py_landlock import AccessFs, Landlock, get_abi_version

    # Network restrictions require ABI 4. Never degrade to unrestricted rendering.
    if get_abi_version() < 4:
        raise ValueError("TeX rendering requires Linux Landlock ABI 4 or newer")
    policy = Landlock().allow_read_write(root).allow_execute(Path(engine).resolve())
    # ELF execution also checks EXECUTE on its interpreter, even when libraries are readable.
    for loader in ["/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-aarch64.so.1"]:
        if Path(loader).exists():
            policy.allow_execute(Path(loader).resolve())
    for path in ["/usr", "/lib", "/lib64", "/etc/texmf", "/etc/fonts", "/var/lib/texmf"]:
        if Path(path).exists():
            policy.allow_read(path)
    for path in ["/dev/null", "/dev/urandom", "/etc/ld.so.cache"]:
        if Path(path).exists():
            policy.add_path_rule(path, access=AccessFs.READ_FILE)
    policy.apply()


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        try:
            restrict_linux(Path.cwd(), sys.argv[1])
        except Exception:
            sys.exit(78)  # Fixed signal to the parent; never expose kernel/private-path errors.
    os.execvp(sys.argv[1], sys.argv[1:])
