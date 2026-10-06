import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import PackageConfig
from .csproj import load_project_roots, read_package_references
from .registries import NpmManifest, PyprojectProjectTable, SENTINEL_VERSION

DEPENDENCY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class DependencyEdge:
    dependency_package: str
    registry: str
    identity: str
    property_name: str | None = None


@dataclass(frozen=True)
class ManifestDependency:
    identity: str
    version: str
    property_name: str | None = None


def resolve_edges(packages: dict[str, PackageConfig]) -> dict[str, list[DependencyEdge]]:
    identity_index: dict[tuple[str, str], str] = {}
    for name, package in packages.items():
        for registry_name, identity in package.registries.items():
            key = (registry_name, identity)
            owner = identity_index.get(key)
            if owner is not None and owner != name:
                raise ValueError(f"packages '{owner}' and '{name}' share {registry_name} identity '{identity}'")
            identity_index[key] = name
    return {name: read_package_edges(name, package, identity_index) for name, package in packages.items()}


def read_package_edges(
    name: str, package: PackageConfig, identity_index: dict[tuple[str, str], str]
) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    for registry_name in package.registries:
        for dependency in MANIFEST_READERS[registry_name](package.path):
            dependency_package = identity_index.get((registry_name, dependency.identity))
            if dependency_package is None:
                if dependency.version == SENTINEL_VERSION:
                    raise ValueError(
                        f"package '{name}': dependency '{dependency.identity}' carries the sentinel "
                        f"'{SENTINEL_VERSION}' but no config package owns that {registry_name} identity"
                    )
                continue
            if dependency.version != SENTINEL_VERSION:
                raise ValueError(
                    f"package '{name}': dependency '{dependency.identity}' resolves to config package "
                    f"'{dependency_package}' and must be authored as the sentinel '{SENTINEL_VERSION}', "
                    f"found '{dependency.version}'"
                )
            edges.append(
                DependencyEdge(
                    dependency_package=dependency_package,
                    registry=registry_name,
                    identity=dependency.identity,
                    property_name=dependency.property_name,
                )
            )
    return edges


def read_npm_manifest(package_path: Path) -> list[ManifestDependency]:
    manifest_path = package_path / "package.json"
    if not manifest_path.is_file():
        raise ValueError(f"no package.json under '{package_path}' but the npm registry is declared")
    manifest = NpmManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    return [
        ManifestDependency(identity=dependency_name, version=dependency_version)
        for dependency_name, dependency_version in manifest.dependencies.items()
    ]


def read_pypi_manifest(package_path: Path) -> list[ManifestDependency]:
    manifest_path = package_path / "pyproject.toml"
    if not manifest_path.is_file():
        raise ValueError(f"no pyproject.toml under '{package_path}' but the pypi registry is declared")
    document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    project_table = PyprojectProjectTable.model_validate(document.get("project", {}))
    dependencies: list[ManifestDependency] = []
    for entry in project_table.dependencies:
        name_match = DEPENDENCY_NAME_PATTERN.match(entry)
        if name_match is None:
            raise ValueError(f"pyproject.toml under '{package_path}' carries unparseable dependency '{entry}'")
        dependency_name = name_match.group(0)
        version = SENTINEL_VERSION if entry == f"{dependency_name}=={SENTINEL_VERSION}" else entry
        dependencies.append(ManifestDependency(identity=dependency_name, version=version))
    return dependencies


def read_nuget_manifest(package_path: Path) -> list[ManifestDependency]:
    dependencies: list[ManifestDependency] = []
    for root in load_project_roots(package_path):
        for reference in read_package_references(root):
            dependencies.append(
                ManifestDependency(
                    identity=reference.identity,
                    version=reference.version,
                    property_name=reference.property_name,
                )
            )
    return dependencies


MANIFEST_READERS: dict[str, Callable[[Path], list[ManifestDependency]]] = {
    "npm": read_npm_manifest,
    "pypi": read_pypi_manifest,
    "nuget": read_nuget_manifest,
}
