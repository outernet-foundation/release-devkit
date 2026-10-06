from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ci_devkit.ci_step import ci_step
from ci_devkit.setup import configure_git, install_dotnet, install_node

from .config import PackageConfig, PublishConfig, write_step_summary
from .manifests import DependencyEdge, resolve_edges
from .tags import parse_major_minor, parse_version

UNCHANGED_FALLBACK_VERSION = "0.0.0"


class TagSource(Protocol):
    def latest_version(self, prefix: str) -> str | None: ...

    def latest_version_in_line(self, prefix: str, major_minor: str) -> str | None: ...

    def has_changes_since(self, tag: str | None, path: Path) -> bool: ...


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

    def anything_releases(self) -> bool:
        return bool(self.publishing) or bool(self.app_versions)


def compute_and_print_plan(config: PublishConfig, tags: TagSource, step_summary: str | None) -> ReleasePlan:
    release_plan = compute_release_plan(config, tags)

    lines = [
        "### Publish Plan",
        "| Package | Publish | Version |",
        "|---|---|---|",
    ]
    lines.extend(f"| {plan.name} | {plan.publish} | {plan.version} |" for plan in release_plan.plans.values())
    lines.extend(["", "### App Versions"])
    for app_name, last_version in release_plan.app_last_versions.items():
        new_version = release_plan.app_versions.get(app_name)
        if new_version is not None:
            lines.append(f"- {app_name}: {last_version or '(none)'} -> {new_version}")
        else:
            lines.append(f"- {app_name}: {last_version or '0.0.0'} (unchanged)")
    summary = "\n".join(lines)

    print(summary)
    write_step_summary(step_summary, summary)
    return release_plan


def compute_release_plan(publish_config: PublishConfig, tags: TagSource) -> ReleasePlan:
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
        last_version = tags.latest_version(prefix)
        last_in_line = tags.latest_version_in_line(prefix, package.major_minor)
        changed = tags.has_changes_since(f"{prefix}{last_version}" if last_version else None, package.path)
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
        last_version = tags.latest_version(prefix)
        last_in_line = tags.latest_version_in_line(prefix, app_config.major_minor)
        app_last_versions[app_name] = last_version
        changed = tags.has_changes_since(f"{prefix}{last_version}" if last_version else None, app_config.path)
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


def setup_publishing_environment(release_plan: ReleasePlan, packages: dict[str, PackageConfig], workspace: str) -> None:
    with ci_step("Setup"):
        configure_git(workspace)
        registries_to_publish = {
            registry_name for name in release_plan.publishing for registry_name in packages[name].registries
        }
        if "nuget" in registries_to_publish:
            install_dotnet("8.0")
        if "npm" in registries_to_publish:
            install_node("24", "https://registry.npmjs.org")


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
