from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from .config import DEFAULT_CONFIG_PATH, load_config
from .create_release import run_create_release
from .draft_releases import DEV_DRAFT_TAG, delete_draft_release
from .outputs import append_line
from .plan import compute_release_plan, render_plan_summary, setup_publishing_environment
from .registries import PublishRequest, build_registries
from .tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_repository: str = ""
    github_workspace: str = ""
    github_step_summary: str | None = None
    nuget_api_key: str = ""


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    packages = publish_config.packages
    tags = GitTags()

    with ci_step("Compute publish plan"):
        release_plan = compute_release_plan(publish_config, tags)
        summary = render_plan_summary(release_plan)
        print(summary)
        append_line(settings.github_step_summary, summary)

    if not release_plan.anything_releases():
        print("Nothing to publish")
        return

    setup_publishing_environment(release_plan, packages, settings.github_workspace)

    if packages:
        registries = build_registries(settings.nuget_api_key)
        for name, package in packages.items():
            plan = release_plan.plans[name]
            if not plan.publish:
                continue
            dependency_versions = {
                identity: resolved.version for identity, resolved in release_plan.resolved_versions[name].items()
            }
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
            plan = release_plan.plans[name]
            if plan.publish:
                tag = f"{name}-v{plan.version}"
                tags.create_and_push_tag(tag)
                print(f"  Tagged: {tag}")

        for app_name, app_version in release_plan.app_versions.items():
            tag = f"{app_name}-v{app_version}"
            tags.create_and_push_tag(tag)
            print(f"  Tagged: {tag}")

    run_create_release(config)
    delete_draft_release(DEV_DRAFT_TAG, settings.github_repository)
