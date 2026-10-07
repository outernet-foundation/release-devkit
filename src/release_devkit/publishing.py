from collections.abc import Callable
from pathlib import Path

from ci_devkit.setup import configure_git, install_dotnet, install_node

from release_devkit.context import VerbContext, merge_push_context
from release_devkit.plan import ReleasePlan, compute_release_plan
from release_devkit.registries import (
    DEV_VERSION_FORMATS,
    NPM_DEV_DIST_TAG,
    PublishRequest,
    build_registries,
)
from release_devkit.tags import create_and_push_tag

REGISTRY_SETUP: dict[str, Callable[[], None]] = {
    "nuget": lambda: install_dotnet("8.0"),
    "npm": lambda: install_node("24", "https://registry.npmjs.org"),
    "pypi": lambda: None,
}


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

    registries_to_publish = {
        registry_name for name in release_plan.publishing for registry_name in packages[name].registries
    }
    configure_git(context.settings.github_workspace)
    for registry_name in sorted(registries_to_publish):
        REGISTRY_SETUP[registry_name]()

    registries = build_registries(context.settings.nuget_api_key)
    for name, package in packages.items():
        plan = release_plan.plans[name]
        if not plan.publish:
            continue
        for registry_name, identity in package.registries.items():
            version = DEV_VERSION_FORMATS[registry_name](plan.version, context.short) if dev else plan.version
            dependency_versions = {
                dep_identity: (
                    DEV_VERSION_FORMATS[registry_name](resolved.version, context.short)
                    if dev and resolved.co_publishing
                    else resolved.version
                )
                for dep_identity, resolved in release_plan.resolved_versions[name].items()
            }
            registries[registry_name].publish(
                PublishRequest(
                    path=package.path,
                    identity=identity,
                    version=version,
                    dependency_versions=dependency_versions,
                    dist_tag=NPM_DEV_DIST_TAG if dev and registry_name == "npm" else None,
                )
            )
            published.append((registry_name, identity, version))
        if not dev:
            create_and_push_tag(f"{name}-v{plan.version}")

    return context, release_plan, published
