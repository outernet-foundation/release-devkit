from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import PackageConfig
from .ledger import parse_major_minor, parse_version
from .manifests import DependencyEdge
from .registries import DEV_VERSION_FORMATS

UNCHANGED_FALLBACK_VERSION = "0.0.0"


class TagLedger(Protocol):
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


def compute_plan(
    packages: dict[str, PackageConfig], ledger: TagLedger, edges: dict[str, list[DependencyEdge]]
) -> dict[str, PackagePlan]:
    plans: dict[str, PackagePlan] = {}
    for name in topological_order(packages, edges):
        package = packages[name]
        prefix = f"{name}-v"
        last_version = ledger.latest_version(prefix)
        last_in_line = ledger.latest_version_in_line(prefix, package.major_minor)
        changed = ledger.has_changes_since(f"{prefix}{last_version}" if last_version else None, package.path)
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
    return plans


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


def topological_order(packages: dict[str, PackageConfig], edges: dict[str, list[DependencyEdge]]) -> list[str]:
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
    return ordered


def next_version(major_minor: str, last_in_line: str | None, last_overall: str | None, subject: str) -> str:
    line = parse_major_minor(major_minor)
    if last_overall is not None and parse_version(last_overall)[:2] > line:
        raise ValueError(
            f"{subject}: declared major.minor {major_minor} is below ledger version {last_overall}; "
            "bump major_minor in release-devkit.json"
        )
    if last_in_line is None:
        return f"{line[0]}.{line[1]}.0"
    major, minor, patch = parse_version(last_in_line)
    return f"{major}.{minor}.{patch + 1}"


def render_summary(plans: dict[str, PackagePlan]) -> str:
    lines = [
        "### Publish Plan",
        "| Package | Publish | Version |",
        "|---|---|---|",
    ]
    lines.extend(f"| {plan.name} | {plan.publish} | {plan.version} |" for plan in plans.values())
    return "\n".join(lines)


def render_dev_summary(packages: dict[str, PackageConfig], plans: dict[str, PackagePlan], run_id: str) -> str:
    lines = [
        "### Dev Publish Plan",
        "| Package | Publish | Versions |",
        "|---|---|---|",
    ]
    for name, package in packages.items():
        plan = plans[name]
        if not plan.publish:
            lines.append(f"| {plan.name} | False | - |")
            continue
        versions = ", ".join(
            f"{registry_name}: {identity} @ {DEV_VERSION_FORMATS[registry_name](plan.version, run_id)}"
            for registry_name, identity in package.registries.items()
        )
        lines.append(f"| {plan.name} | True | {versions} |")
    return "\n".join(lines)
