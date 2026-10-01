import json
import re
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from typing import Protocol

from bashrun.bash import bash, bash_output
from pydantic import BaseModel, ConfigDict, Field

from .csproj import load_project_roots, read_package_references

NUGET_SOURCE = "https://api.nuget.org/v3/index.json"
PYPI_SIMPLE_INDEX = "https://pypi.org/simple/"
PYPROJECT_VERSION_PATTERN = re.compile(r'^version\s*=\s*"[^"]*"')
NPM_DEV_DIST_TAG = "dev"
# Same-unit dependency sentinel: authored in manifests, injected with the event version at publish.
SENTINEL_VERSION = "0.0.0+local"


class NpmManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str = ""
    dependencies: dict[str, str] = Field(default_factory=dict)


class PyprojectProjectTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dependencies: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PublishRequest:
    path: Path
    identity: str
    version: str
    dependency_versions: dict[str, str]
    dist_tag: str | None = None


class Registry(Protocol):
    def publish(self, request: PublishRequest) -> None: ...


class NuGetRegistry:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def publish(self, request: PublishRequest) -> None:
        properties = nuget_injection_properties(request.path, request.dependency_versions)
        command = f"dotnet pack -c Release -p:Version={request.version}"
        if properties:
            property_flags = " ".join(f"-p:{name}={version}" for name, version in properties.items())
            command += f" {property_flags}"
        # Pack outside the package root — NpmRegistry.publish packs request.path next, and a
        # .nupkg written there rides the npm tarball (bin/obj are relocated out for the same reason).
        with tempfile.TemporaryDirectory() as outdir:
            command += f" -o {outdir}"
            bash(command, cwd=request.path)
            bash(
                f"dotnet nuget push {outdir}/*.nupkg --api-key {self.api_key} --source {NUGET_SOURCE} --skip-duplicate",
                cwd=request.path,
            )


class NpmRegistry:
    def publish(self, request: PublishRequest) -> None:
        command = "npm publish --access public --provenance --loglevel verbose"
        if request.dist_tag:
            command += f" --tag {request.dist_tag}"
        with ephemeral_manifest_patch(request.path, request.version, request.dependency_versions):
            try:
                bash_output(command, cwd=request.path)
            except CalledProcessError as e:
                stderr = e.stderr or ""
                if "EPUBLISHCONFLICT" in stderr or "cannot publish over" in stderr:
                    print("  Version already published, skipping (idempotent)")
                else:
                    raise


class PyPIRegistry:
    def publish(self, request: PublishRequest) -> None:
        with ephemeral_pyproject_patch(request.path, request.version, request.dependency_versions):
            bash("uv build --out-dir dist", cwd=request.path)
        bash(f"uv publish --check-url {PYPI_SIMPLE_INDEX}", cwd=request.path)


@contextmanager
def ephemeral_manifest_patch(package_path: Path, version: str, dependency_versions: dict[str, str]) -> Generator[None]:
    manifest_path = package_path / "package.json"
    original = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = NpmManifest.model_validate(json.loads(original))
        manifest.version = version
        for dependency_name, dependency_version in dependency_versions.items():
            if dependency_name in manifest.dependencies:
                manifest.dependencies[dependency_name] = dependency_version
        manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2) + "\n", encoding="utf-8")
        yield
    finally:
        manifest_path.write_text(original, encoding="utf-8")


@contextmanager
def ephemeral_pyproject_patch(package_path: Path, version: str, dependency_versions: dict[str, str]) -> Generator[None]:
    manifest_path = package_path / "pyproject.toml"
    original = manifest_path.read_text(encoding="utf-8")
    try:
        patched = patch_project_dependencies(original, dependency_versions)
        manifest_path.write_text(patch_project_version(patched, version), encoding="utf-8")
        yield
    finally:
        manifest_path.write_text(original, encoding="utf-8")


def patch_project_version(original: str, version: str) -> str:
    lines = original.splitlines(keepends=True)
    in_project_table = False
    for index, line in enumerate(lines):
        if line.startswith("["):
            in_project_table = line.strip() == "[project]"
            continue
        if in_project_table and PYPROJECT_VERSION_PATTERN.match(line):
            lines[index] = f'version = "{version}"\n'
            return "".join(lines)
    raise ValueError("pyproject.toml carries no [project] version to patch")


def patch_project_dependencies(original: str, dependency_versions: dict[str, str]) -> str:
    patched = original
    for dependency_name, dependency_version in dependency_versions.items():
        sentinel_specifier = f"{dependency_name}=={SENTINEL_VERSION}"
        if sentinel_specifier in patched:
            patched = patched.replace(sentinel_specifier, f"{dependency_name}=={dependency_version}")
    return patched


KNOWN_REGISTRIES = frozenset({"nuget", "npm", "pypi"})


def semver_dev_version(base_version: str, run_id: str) -> str:
    return f"{base_version}-dev.{run_id}"


def pep440_dev_version(base_version: str, run_id: str) -> str:
    return f"{base_version}.dev{run_id}"


DEV_VERSION_FORMATS: dict[str, Callable[[str, str], str]] = {
    "nuget": semver_dev_version,
    "npm": semver_dev_version,
    "pypi": pep440_dev_version,
}


def build_registries(nuget_api_key: str) -> dict[str, Registry]:
    return {"nuget": NuGetRegistry(nuget_api_key), "npm": NpmRegistry(), "pypi": PyPIRegistry()}


def nuget_injection_properties(package_path: Path, dependency_versions: dict[str, str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    found: set[str] = set()
    for root in load_project_roots(package_path):
        for reference in read_package_references(root):
            if reference.identity not in dependency_versions:
                continue
            if reference.property_name is None:
                raise ValueError(
                    f"package reference '{reference.identity}' carries literal version "
                    f"'{reference.version}'; same-unit references must use a '$(Property)' version"
                )
            properties[reference.property_name] = dependency_versions[reference.identity]
            found.add(reference.identity)
    missing = set(dependency_versions) - found
    if missing:
        raise ValueError(f"no PackageReference found for {sorted(missing)} under '{package_path}'")
    return properties
