import re
from pathlib import Path

from bashrun.bash import bash, bash_check, bash_output

# Prerelease-suffixed tags (e.g. 1.0.6-preview) are not stable versions: the stable flow
# must never compute a next version from one. Dev-channel versions never enter the tag space.
STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def latest_version(prefix: str) -> str | None:
    for version in list_tag_versions(prefix):
        if STABLE_VERSION_PATTERN.fullmatch(version):
            return version
    return None


def latest_version_in_line(prefix: str, major_minor: str) -> str | None:
    line = parse_major_minor(major_minor)
    for version in list_tag_versions(prefix):
        if STABLE_VERSION_PATTERN.fullmatch(version) and parse_version(version)[:2] == line:
            return version
    return None


def has_changes_since(tag: str | None, path: Path) -> bool:
    if tag is None:
        return True
    return not bash_check(f"git diff --quiet {tag} HEAD -- {path}")


def create_and_push_tag(tag: str) -> None:
    bash(f"git tag {tag}")
    bash(f"git push origin {tag}")


def parse_version(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def parse_major_minor(major_minor: str) -> tuple[int, int]:
    major, minor = (int(part) for part in major_minor.split("."))
    return major, minor


def list_tag_versions(prefix: str) -> list[str]:
    output = bash_output(f'git tag --list "{prefix}*" --sort=-v:refname').strip()
    if not output:
        return []
    return [tag[len(prefix) :] for tag in output.splitlines()]
