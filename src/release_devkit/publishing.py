from pathlib import Path

from ci_devkit.setup import configure_git, install_dotnet, install_node

from release_devkit.context import VerbContext, merge_push_context
from release_devkit.plan import ReleasePlan, compute_release_plan
from release_devkit.registries import Registry, build_registries
from release_devkit.tags import create_and_push_tag


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
            registry = registries[registry_name]
            version = dev_spelling(registry, plan.version, context.short, dev)
            dependency_versions = {
                dep_identity: dev_spelling(registry, resolved.version, context.short, dev and resolved.co_publishing)
                for dep_identity, resolved in release_plan.resolved_versions[name].items()
            }
            registry.publish(package.path, version, dependency_versions, dev)
            published.append((registry_name, identity, version))
        if not dev:
            create_and_push_tag(f"{name}-v{plan.version}")

    return context, release_plan, published


def dev_spelling(registry: Registry, base_version: str, short_sha: str, dev: bool) -> str:
    return registry.dev_version(base_version, short_sha) if dev else base_version
