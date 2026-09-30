from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step
from ci_devkit.setup import configure_git, free_disk_space, install_dotnet, install_node

from .config import DEFAULT_CONFIG_PATH, load_config, select_packages
from .ledger import GitLedger
from .manifests import resolve_edges
from .outputs import append_line
from .plan import compute_plan, render_dev_summary, resolve_dependency_versions
from .registries import DEV_VERSION_FORMATS, NPM_DEV_DIST_TAG, PublishRequest, build_registries

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_workspace: str = ""
    github_step_summary: str | None = None
    github_run_id: str = ""
    nuget_api_key: str = ""


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
    dry_run: Annotated[bool, typer.Option(help="Plan publishes without executing them")] = False,
    run_id: Annotated[
        str, typer.Option(help="CI run id baked into every dev version (defaults to the ambient CI run id)")
    ] = "",
    only: Annotated[list[str] | None, typer.Option(help="Restrict to named packages (repeatable).")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Skip named packages (repeatable).")] = None,
) -> None:
    settings = Settings.model_validate({})
    resolved_run_id = run_id or settings.github_run_id
    if not resolved_run_id.isdigit():
        raise SystemExit("dev run id must be all digits: pass --run-id or run inside CI")

    publish_config = load_config(config)
    packages = select_packages(publish_config.packages, only or [], exclude or [])
    ledger = GitLedger()

    with ci_step("Compute dev publish plan"):
        edges = resolve_edges(publish_config.packages)
        plans = compute_plan(publish_config.packages, ledger, edges)
        publishing = {name for name in packages if plans[name].publish}
        resolved_versions = {
            name: resolve_dependency_versions(edges[name], plans, publishing) for name in packages if name in publishing
        }

        summary = render_dev_summary(packages, plans, resolved_run_id)
        print(summary)
        append_line(settings.github_step_summary, summary)

        if not any(plan.publish for plan in plans.values()):
            print("Nothing to publish")
            return

        if dry_run:
            print("Dry run — skipping publish")
            return

    with ci_step("Setup"):
        configure_git(settings.github_workspace)
        free_disk_space()
        install_dotnet("8.0")
        install_node("24", "https://registry.npmjs.org")

    registries = build_registries(settings.nuget_api_key)
    published: list[tuple[str, str, str]] = []
    for name, package in packages.items():
        plan = plans[name]
        if not plan.publish:
            continue
        for registry_name, identity in package.registries.items():
            dev_version = DEV_VERSION_FORMATS[registry_name](plan.version, resolved_run_id)
            with ci_step(f"Publish {registry_name} ({name}) {dev_version}"):
                registries[registry_name].publish(
                    PublishRequest(
                        path=package.path,
                        identity=identity,
                        version=dev_version,
                        dependency_versions={
                            dependency_identity: (
                                DEV_VERSION_FORMATS[registry_name](resolved.version, resolved_run_id)
                                if resolved.co_publishing
                                else resolved.version
                            )
                            for dependency_identity, resolved in resolved_versions[name].items()
                        },
                        dist_tag=NPM_DEV_DIST_TAG if registry_name == "npm" else None,
                    )
                )
            published.append((registry_name, identity, dev_version))

    recap = "\n".join([
        "### Published dev versions",
        *(f"{registry_name}: {identity} @ {version}" for registry_name, identity, version in published),
    ])
    print(recap)
    print("Consume these by exact version pin - there is no discovery tooling by design")
    append_line(settings.github_step_summary, recap)
