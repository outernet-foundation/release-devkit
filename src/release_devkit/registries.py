import json
import re
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError
from typing import Protocol

from bashrun.bash import bash, bash_output
from pydantic import BaseModel, ConfigDict, Field

from release_devkit.csproj import load_project_roots, read_package_references

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


class Registry(Protocol):
    def publish(
        self,
        path: Path,
        version: str,
        dependency_versions: dict[str, str],
        dist_tag: str | None = None,
    ) -> None: ...


class NuGetRegistry:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def publish(
        self,
        path: Path,
        version: str,
        dependency_versions: dict[str, str],
        dist_tag: str | None = None,
    ) -> None:
        properties: dict[str, str] = {}
        found: set[str] = set()
        for root in load_project_roots(path):
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
            raise ValueError(f"no PackageReference found for {sorted(missing)} under '{path}'")

        command = f"dotnet pack -c Release -p:Version={version}"
        if properties:
            property_flags = " ".join(f"-p:{name}={version}" for name, version in properties.items())
            command += f" {property_flags}"
        # Pack outside the package root — NpmRegistry.publish packs path next, and a
        # .nupkg written there rides the npm tarball (bin/obj are relocated out for the same reason).
        with tempfile.TemporaryDirectory() as outdir:
            command += f" -o {outdir}"
            bash(command, cwd=path)
            try:
                bash(
                    f"dotnet nuget push {outdir}/*.nupkg --api-key {self.api_key}"
                    f" --source {NUGET_SOURCE} --skip-duplicate",
                    cwd=path,
                )
            except CalledProcessError as error:
                # The push command interpolates the api key; a raised CalledProcessError renders
                # the command text into CI logs. Re-raise with the exit code and first stderr
                # line only — never the command.
                stderr_lines = [line.strip() for line in (error.stderr or "").splitlines() if line.strip()]
                detail = stderr_lines[0] if stderr_lines else "no stderr output"
                raise SystemExit(f"dotnet nuget push failed (exit {error.returncode}): {detail}") from None


class NpmRegistry:
    def publish(
        self,
        path: Path,
        version: str,
        dependency_versions: dict[str, str],
        dist_tag: str | None = None,
    ) -> None:
        command = "npm publish --access public --provenance --loglevel verbose"
        if dist_tag:
            command += f" --tag {dist_tag}"
        with ephemeral_manifest_patch(path, version, dependency_versions):
            try:
                bash_output(command, cwd=path)
            except CalledProcessError as e:
                stderr = e.stderr or ""
                if "EPUBLISHCONFLICT" in stderr or "cannot publish over" in stderr:
                    print("  Version already published, skipping (idempotent)")
                else:
                    raise


class PyPIRegistry:
    def publish(
        self,
        path: Path,
        version: str,
        dependency_versions: dict[str, str],
        dist_tag: str | None = None,
    ) -> None:
        with ephemeral_pyproject_patch(path, version, dependency_versions):
            bash("uv build --out-dir dist", cwd=path)
        bash(f"uv publish --check-url {PYPI_SIMPLE_INDEX}", cwd=path)


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
        patched = original
        for dependency_name, dependency_version in dependency_versions.items():
            sentinel_specifier = f"{dependency_name}=={SENTINEL_VERSION}"
            if sentinel_specifier in patched:
                patched = patched.replace(sentinel_specifier, f"{dependency_name}=={dependency_version}")
        lines = patched.splitlines(keepends=True)
        in_project_table = False
        for index, line in enumerate(lines):
            if line.startswith("["):
                in_project_table = line.strip() == "[project]"
                continue
            if in_project_table and PYPROJECT_VERSION_PATTERN.match(line):
                lines[index] = f'version = "{version}"\n'
                patched = "".join(lines)
                break
        else:
            raise ValueError("pyproject.toml carries no [project] version to patch")
        manifest_path.write_text(patched, encoding="utf-8")
        yield
    finally:
        manifest_path.write_text(original, encoding="utf-8")


KNOWN_REGISTRIES = frozenset({"nuget", "npm", "pypi"})

REGISTRY_URL_TEMPLATES: dict[str, str] = {
    "nuget": "https://www.nuget.org/packages/{0}/{1}",
    "npm": "https://www.npmjs.com/package/{0}/v/{1}",
    "pypi": "https://pypi.org/project/{0}/{1}",
}


def registry_url(registry_name: str, identity: str, version: str) -> str | None:
    template = REGISTRY_URL_TEMPLATES.get(registry_name)
    if template is None:
        return None
    return template.format(identity, version)


def semver_dev_version(base_version: str, short_sha: str) -> str:
    return f"{base_version}-dev.{short_sha}"


def pep440_dev_version(base_version: str, short_sha: str) -> str:
    return f"{base_version}.dev{short_sha}"


DEV_VERSION_FORMATS: dict[str, Callable[[str, str], str]] = {
    "nuget": semver_dev_version,
    "npm": semver_dev_version,
    "pypi": pep440_dev_version,
}


def build_registries(nuget_api_key: str) -> dict[str, Registry]:
    return {"nuget": NuGetRegistry(nuget_api_key), "npm": NpmRegistry(), "pypi": PyPIRegistry()}
