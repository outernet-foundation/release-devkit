from typing import Protocol

from ci_devkit.ci_step import ci_step

from .config import PackageConfig
from .plan import PackagePlan, ReleasePlan, ResolvedDependency
from .registries import (
    DEV_VERSION_FORMATS,
    NPM_DEV_DIST_TAG,
    PublishRequest,
    build_registries,
)


class VersionStrategy(Protocol):
    def package_version(self, registry_name: str, plan: PackagePlan) -> str: ...

    def dependency_version(self, resolved: ResolvedDependency, registry_name: str) -> str: ...

    def dist_tag(self, registry_name: str) -> str | None: ...


class StableStrategy:
    def package_version(self, registry_name: str, plan: PackagePlan) -> str:
        return plan.version

    def dependency_version(self, resolved: ResolvedDependency, registry_name: str) -> str:
        return resolved.version

    def dist_tag(self, registry_name: str) -> str | None:
        return None


class DevStrategy:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id

    def package_version(self, registry_name: str, plan: PackagePlan) -> str:
        return DEV_VERSION_FORMATS[registry_name](plan.version, self._run_id)

    def dependency_version(self, resolved: ResolvedDependency, registry_name: str) -> str:
        if resolved.co_publishing:
            return DEV_VERSION_FORMATS[registry_name](resolved.version, self._run_id)
        return resolved.version

    def dist_tag(self, registry_name: str) -> str | None:
        return NPM_DEV_DIST_TAG if registry_name == "npm" else None


def publish_packages(
    packages: dict[str, PackageConfig],
    release_plan: ReleasePlan,
    nuget_api_key: str,
    strategy: VersionStrategy,
) -> list[tuple[str, str, str]]:
    registries = build_registries(nuget_api_key)
    published: list[tuple[str, str, str]] = []
    for name, package in packages.items():
        plan = release_plan.plans[name]
        if not plan.publish:
            continue
        for registry_name, identity in package.registries.items():
            version = strategy.package_version(registry_name, plan)
            with ci_step(f"Publish {registry_name} ({name}) {version}"):
                dependency_versions = {
                    dep_identity: strategy.dependency_version(resolved, registry_name)
                    for dep_identity, resolved in release_plan.resolved_versions[name].items()
                }
                registries[registry_name].publish(
                    PublishRequest(
                        path=package.path,
                        identity=identity,
                        version=version,
                        dependency_versions=dependency_versions,
                        dist_tag=strategy.dist_tag(registry_name),
                    )
                )
            published.append((registry_name, identity, version))
    return published
