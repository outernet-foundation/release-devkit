from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step
from ci_devkit.setup import configure_git, free_disk_space, install_dotnet, install_node

from .config import DEFAULT_CONFIG_PATH, load_config, select_packages
from .create_release import run_create_release
from .ledger import GitLedger
from .manifests import resolve_edges
from .outputs import append_line
from .plan import compute_plan, next_version, render_summary, resolve_dependency_versions
from .registries import PublishRequest, build_registries

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_workspace: str = ""
    github_step_summary: str | None = None
    nuget_api_key: str = ""


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
    dry_run: Annotated[bool, typer.Option(help="Plan publishes without executing them")] = False,
    only: Annotated[list[str] | None, typer.Option(help="Restrict to named packages (repeatable).")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Skip named packages (repeatable).")] = None,
    with_apps: Annotated[bool, typer.Option(help="Handle app version bumps and tags in a filtered run.")] = False,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    packages = select_packages(publish_config.packages, only or [], exclude or [])
    ledger = GitLedger()
    handle_apps = (not only and not exclude) or with_apps

    with ci_step("Compute publish plan"):
        edges = resolve_edges(publish_config.packages)
        plans = compute_plan(publish_config.packages, ledger, edges)
        publishing = {name for name in packages if plans[name].publish}
        resolved_versions = {
            name: resolve_dependency_versions(edges[name], plans, publishing) for name in packages if name in publishing
        }

        summary = render_summary(plans)
        print(summary)
        append_line(settings.github_step_summary, summary)

    any_package_published = any(plans[name].publish for name in packages)
    app_versions: dict[str, str] = {}
    if handle_apps:
        with ci_step("Compute app versions"):
            for app_name, app_config in publish_config.apps.items():
                prefix = f"{app_name}-v"
                last_version = ledger.latest_version(prefix)
                last_in_line = ledger.latest_version_in_line(prefix, app_config.major_minor)
                changed = ledger.has_changes_since(f"{prefix}{last_version}" if last_version else None, app_config.path)
                # Apps depend on packages — bump if any package changed
                if any_package_published:
                    changed = True
                if changed:
                    new_version = next_version(app_config.major_minor, last_in_line, last_version, app_name)
                    app_versions[app_name] = new_version
                    print(f"  {app_name}: {last_version or '(none)'} -> {new_version}")
                else:
                    print(f"  {app_name}: {last_version or '0.0.0'} (unchanged)")

    if not any_package_published and not app_versions:
        print("Nothing to publish")
        return

    if dry_run:
        print("Dry run — skipping publish")
        return

    with ci_step("Setup"):
        configure_git(settings.github_workspace)
        if packages:
            free_disk_space()
            install_dotnet("8.0")
            install_node("24", "https://registry.npmjs.org")

    if packages:
        registries = build_registries(settings.nuget_api_key)
        for name, package in packages.items():
            plan = plans[name]
            if not plan.publish:
                continue
            dependency_versions = {identity: resolved.version for identity, resolved in resolved_versions[name].items()}
            for registry_name, identity in package.registries.items():
                with ci_step(f"Publish {registry_name} ({name})"):
                    registries[registry_name].publish(
                        PublishRequest(
                            path=package.path,
                            identity=identity,
                            version=plan.version,
                            dependency_versions=dependency_versions,
                        )
                    )

    with ci_step("Create version tags"):
        for name in packages:
            plan = plans[name]
            if plan.publish:
                tag = f"{name}-v{plan.version}"
                ledger.create_and_push_tag(tag)
                print(f"  Tagged: {tag}")

        if handle_apps:
            for app_name in publish_config.apps:
                if app_name in app_versions:
                    tag = f"{app_name}-v{app_versions[app_name]}"
                    ledger.create_and_push_tag(tag)
                    print(f"  Tagged: {tag}")

    run_create_release(config)
