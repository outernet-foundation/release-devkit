from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bashrun.bash import bash_check, bash_output

from release_devkit.config import PublishConfig
from release_devkit.manifests import DependencyEdge, resolve_edges

UNCHANGED_FALLBACK_VERSION = "0.0.0"

# Prerelease-suffixed tags (e.g. 1.0.6-preview) are not stable versions: the stable flow
# must never compute a next version from one. Dev-channel versions never enter the tag space.
STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class PackagePlan:
    name: str
    publish: bool
    version: str
    last_version: str | None


@dataclass(frozen=True)
class ResolvedDependency:
    version: str
    co_publishing: bool


@dataclass(frozen=True)
class ReleasePlan:
    plans: dict[str, PackagePlan]
    publishing: set[str]
    resolved_versions: dict[str, dict[str, ResolvedDependency]]
    app_last_versions: dict[str, str | None]
    app_versions: dict[str, str]

    @classmethod
    def empty(cls) -> ReleasePlan:
        return cls(
            plans={},
            publishing=set(),
            resolved_versions={},
            app_last_versions={},
            app_versions={},
        )


def compute_release_plan(publish_config: PublishConfig) -> ReleasePlan:
    packages = publish_config.packages
    edges = resolve_edges(packages)

    dependencies = {name: {edge.dependency_package for edge in edges.get(name, [])} for name in packages}
    ordered: list[str] = []
    placed: set[str] = set()
    remaining = list(packages)
    while remaining:
        ready = next((name for name in remaining if dependencies[name] <= placed), None)
        if ready is None:
            raise ValueError(f"cyclic dependency edge among packages: {sorted(remaining)}")
        ordered.append(ready)
        placed.add(ready)
        remaining.remove(ready)

    plans: dict[str, PackagePlan] = {}
    for name in ordered:
        package = packages[name]
        prefix = f"{name}-v"
        last_version = get_latest_version(prefix)
        last_in_line = latest_version_in_line(prefix, package.major_minor)
        changed = has_changes_since(f"{prefix}{last_version}" if last_version else None, package.path)
        plans[name] = PackagePlan(
            name=name,
            publish=changed,
            version=(
                next_version(package.major_minor, last_in_line, last_version, name)
                if changed
                else (last_version or UNCHANGED_FALLBACK_VERSION)
            ),
            last_version=last_version,
        )

    publishing = {name for name in packages if plans[name].publish}
    resolved_versions = {
        name: resolve_dependency_versions(edges[name], plans, publishing) for name in packages if name in publishing
    }
    any_package_published = any(plans[name].publish for name in packages)
    app_last_versions: dict[str, str | None] = {}
    app_versions: dict[str, str] = {}
    for app_name, app_config in publish_config.apps.items():
        prefix = f"{app_name}-v"
        last_version = get_latest_version(prefix)
        last_in_line = latest_version_in_line(prefix, app_config.major_minor)
        app_last_versions[app_name] = last_version
        changed = has_changes_since(f"{prefix}{last_version}" if last_version else None, app_config.path)
        if any_package_published:
            changed = True
        if changed:
            app_versions[app_name] = next_version(app_config.major_minor, last_in_line, last_version, app_name)
    return ReleasePlan(
        plans=plans,
        publishing=publishing,
        resolved_versions=resolved_versions,
        app_last_versions=app_last_versions,
        app_versions=app_versions,
    )


def resolve_dependency_versions(
    package_edges: list[DependencyEdge], plans: dict[str, PackagePlan], publishing: set[str]
) -> dict[str, ResolvedDependency]:
    resolved: dict[str, ResolvedDependency] = {}
    for edge in package_edges:
        dependency_plan = plans[edge.dependency_package]
        if edge.dependency_package in publishing:
            resolved[edge.identity] = ResolvedDependency(version=dependency_plan.version, co_publishing=True)
            continue
        if dependency_plan.last_version is None:
            raise ValueError(
                f"dependency '{edge.dependency_package}' has never published; "
                "publish it first or include it in this run"
            )
        resolved[edge.identity] = ResolvedDependency(version=dependency_plan.last_version, co_publishing=False)
    return resolved


def next_version(major_minor: str, last_in_line: str | None, last_overall: str | None, subject: str) -> str:
    line = parse_major_minor(major_minor)
    if last_overall is not None and parse_version(last_overall)[:2] > line:
        raise ValueError(
            f"{subject}: declared major.minor {major_minor} is below tags version {last_overall}; "
            "bump major_minor in release-devkit.yaml"
        )
    if last_in_line is None:
        return f"{line[0]}.{line[1]}.0"
    major, minor, patch = parse_version(last_in_line)
    return f"{major}.{minor}.{patch + 1}"


def get_latest_version(prefix: str) -> str | None:
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


def list_tag_versions(prefix: str) -> list[str]:
    output = bash_output(f'git tag --list "{prefix}*" --sort=-v:refname').strip()
    if not output:
        return []
    return [tag[len(prefix) :] for tag in output.splitlines()]


def parse_version(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def parse_major_minor(major_minor: str) -> tuple[int, int]:
    major, minor = (int(part) for part in major_minor.split("."))
    return major, minor
