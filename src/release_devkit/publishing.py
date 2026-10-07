import json
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError
from typing import Protocol

from bashrun.bash import bash, bash_output
from ci_devkit.setup import configure_git, install_dotnet, install_node

from release_devkit.context import VerbContext, merge_push_context
from release_devkit.csproj import load_project_roots, read_package_references
from release_devkit.manifests import NpmManifest, SENTINEL_VERSION
from release_devkit.plan import ReleasePlan, ResolvedDependency, compute_release_plan
from release_devkit.tags import create_and_push_tag

NUGET_SOURCE = "https://api.nuget.org/v3/index.json"
PYPI_SIMPLE_INDEX = "https://pypi.org/simple/"
PYPROJECT_VERSION_PATTERN = re.compile(r'^version\s*=\s*"[^"]*"')
NPM_DEV_DIST_TAG = "dev"


def deliver_changed_packages(
    config: Path,
    dev: bool,
) -> tuple[VerbContext, ReleasePlan, list[tuple[str, str, str]]]:
    context = merge_push_context(config)
    packages = context.publish_config.packages
    release_plan = compute_release_plan(context.publish_config)

    published: list[tuple[str, str, str]] = []
    if not release_plan.publishing:
        return context, release_plan, published

    configure_git(context.settings.github_workspace)
    if "nuget" in release_plan.publishing_registries:
        install_dotnet("8.0")
    if "npm" in release_plan.publishing_registries:
        install_node("24", "https://registry.npmjs.org")

    registries = build_registries(context.settings.nuget_api_key)
    for name, package in packages.items():
        plan = release_plan.plans[name]
        if not plan.publish:
            continue
        for registry_name, identity in package.registries.items():
            published.append((
                registry_name,
                identity,
                registries[registry_name].publish(
                    package.path, plan.version, release_plan.resolved_versions[name], dev, context.short
                ),
            ))
        if not dev:
            create_and_push_tag(f"{name}-v{plan.version}")

    return context, release_plan, published


class Registry(Protocol):
    def dev_version(self, base_version: str, short_sha: str) -> str: ...

    def publish(
        self,
        path: Path,
        base_version: str,
        resolved_dependencies: dict[str, ResolvedDependency],
        dev: bool,
        short_sha: str,
    ) -> str: ...


class NuGetRegistry:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def dev_version(self, base_version: str, short_sha: str) -> str:
        return semver_dev_version(base_version, short_sha)

    def publish(
        self,
        path: Path,
        base_version: str,
        resolved_dependencies: dict[str, ResolvedDependency],
        dev: bool,
        short_sha: str,
    ) -> str:
        version, dependency_versions = resolve_publish_versions(
            self, base_version, short_sha, dev, resolved_dependencies
        )
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
        return version


class NpmRegistry:
    def dev_version(self, base_version: str, short_sha: str) -> str:
        return semver_dev_version(base_version, short_sha)

    def publish(
        self,
        path: Path,
        base_version: str,
        resolved_dependencies: dict[str, ResolvedDependency],
        dev: bool,
        short_sha: str,
    ) -> str:
        version, dependency_versions = resolve_publish_versions(
            self, base_version, short_sha, dev, resolved_dependencies
        )
        command = "npm publish --access public --provenance --loglevel verbose"
        if dev:
            command += f" --tag {NPM_DEV_DIST_TAG}"
        with ephemeral_manifest_patch(path, version, dependency_versions):
            try:
                bash_output(command, cwd=path)
            except CalledProcessError as e:
                stderr = e.stderr or ""
                if "EPUBLISHCONFLICT" in stderr or "cannot publish over" in stderr:
                    print("  Version already published, skipping (idempotent)")
                else:
                    raise
        return version


class PyPIRegistry:
    def dev_version(self, base_version: str, short_sha: str) -> str:
        return pep440_dev_version(base_version, short_sha)

    def publish(
        self,
        path: Path,
        base_version: str,
        resolved_dependencies: dict[str, ResolvedDependency],
        dev: bool,
        short_sha: str,
    ) -> str:
        version, dependency_versions = resolve_publish_versions(
            self, base_version, short_sha, dev, resolved_dependencies
        )
        with ephemeral_pyproject_patch(path, version, dependency_versions):
            bash("uv build --out-dir dist", cwd=path)
        bash(f"uv publish --check-url {PYPI_SIMPLE_INDEX}", cwd=path)
        return version


def resolve_publish_versions(
    registry: Registry,
    base_version: str,
    short_sha: str,
    dev: bool,
    resolved_dependencies: dict[str, ResolvedDependency],
) -> tuple[str, dict[str, str]]:
    version = registry.dev_version(base_version, short_sha) if dev else base_version
    dependency_versions = {
        identity: registry.dev_version(resolved.version, short_sha)
        if dev and resolved.co_publishing
        else resolved.version
        for identity, resolved in resolved_dependencies.items()
    }
    return version, dependency_versions


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


def semver_dev_version(base_version: str, short_sha: str) -> str:
    return f"{base_version}-dev.{short_sha}"


def pep440_dev_version(base_version: str, short_sha: str) -> str:
    return f"{base_version}.dev{short_sha}"


def build_registries(nuget_api_key: str) -> dict[str, Registry]:
    return {"nuget": NuGetRegistry(nuget_api_key), "npm": NpmRegistry(), "pypi": PyPIRegistry()}
