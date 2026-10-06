from __future__ import annotations

import platform
from pathlib import Path

from bashrun.bash import CalledProcessError, bash, bash_output

ACTIONLINT_VERSION = "1.7.12"

ACTIONLINT_BUILDS = {
    ("Linux", "x86_64"): "linux_amd64",
    ("Linux", "aarch64"): "linux_arm64",
    ("Darwin", "x86_64"): "darwin_amd64",
    ("Darwin", "arm64"): "darwin_arm64",
}


def run_actionlint() -> None:
    workflows_directory = Path(".github/workflows")
    workflow_files = sorted(workflows_directory.glob("*.yml")) if workflows_directory.is_dir() else []
    if not workflow_files:
        raise SystemExit("no .github/workflows/*.yml files found")
    binary = ensure_actionlint()
    command = " ".join([f'"{binary}"', *[f'"{workflow_file}"' for workflow_file in workflow_files]])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def ensure_actionlint() -> Path:
    cache_directory = Path.home() / ".cache" / "release-devkit" / f"actionlint-v{ACTIONLINT_VERSION}"
    binary = cache_directory / "actionlint"
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in ACTIONLINT_BUILDS:
        raise SystemExit(f"no actionlint build for {platform.system()}/{platform.machine()}")
    build = ACTIONLINT_BUILDS[platform_key]
    release_base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
    tarball_name = f"actionlint_{ACTIONLINT_VERSION}_{build}.tar.gz"
    tarball = cache_directory / tarball_name
    bash(f'curl -fsSL {release_base}/{tarball_name} -o "{tarball}"')
    checksums = bash_output(f"curl -fsSL {release_base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt")
    expected = expected_checksum(checksums, tarball_name)
    actual = bash_output(f'sha256sum "{tarball}"').split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(
            f"actionlint {ACTIONLINT_VERSION} checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
        )
    bash(f'tar -xzf "{tarball}" -C "{cache_directory}"')
    tarball.unlink()
    if not binary.is_file():
        raise SystemExit(f"actionlint binary missing after extracting {tarball_name}")
    return binary


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")
