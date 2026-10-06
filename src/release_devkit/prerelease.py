from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step
from ci_devkit.setup import configure_git, free_disk_space, install_dotnet, install_node

from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config, select_packages
from .create_release import matched_ci_run_number, pull_build_assets
from .draft_releases import (
    DEV_DRAFT_TAG,
    append_draft_section,
    emit_draft_backlink,
    ensure_draft_release,
    stage_draft_assets,
    upload_draft_assets,
)
from .outputs import append_line
from .plan import TagSource, compute_release_plan, render_dev_summary
from .registries import DEV_VERSION_FORMATS, NPM_DEV_DIST_TAG, PublishRequest, build_registries, registry_url
from .tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


class Settings(BaseSettings):
    github_repository: str = ""
    github_sha: str = ""
    github_actor: str = ""
    github_token: str = ""
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
    tags = GitTags()

    with ci_step("Compute dev publish plan"):
        release_plan = compute_release_plan(publish_config, packages, tags)

        summary = render_dev_summary(packages, release_plan.plans, resolved_run_id)
        print(summary)
        append_line(settings.github_step_summary, summary)

        changed_apps = {
            name: app
            for name, app in publish_config.apps.items()
            if app.builds is not None and app_has_changes(tags, name, app)
        }
        has_package_changes = release_plan.publishing
        has_app_changes = bool(changed_apps)
        if not has_package_changes and not has_app_changes:
            print("Nothing to publish")
            return

        if dry_run:
            print("Dry run — skipping publish")
            return

    published: list[tuple[str, str, str]] = []
    if has_package_changes:
        with ci_step("Setup"):
            configure_git(settings.github_workspace)
            free_disk_space()
            install_dotnet("8.0")
            install_node("24", "https://registry.npmjs.org")

        registries = build_registries(settings.nuget_api_key)
        for name, package in packages.items():
            plan = release_plan.plans[name]
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
                                for dependency_identity, resolved in release_plan.resolved_versions[name].items()
                            },
                            dist_tag=NPM_DEV_DIST_TAG if registry_name == "npm" else None,
                        )
                    )
                published.append((registry_name, identity, dev_version))

        if published:
            recap = "\n".join([
                "### Published dev versions",
                *(f"{registry_name}: {identity} @ {version}" for registry_name, identity, version in published),
            ])
            print(recap)
            print("Consume these by exact version pin - there is no discovery tooling by design")
            append_line(settings.github_step_summary, recap)

    staged_assets: list[tuple[str, Path]] = []
    if has_app_changes:
        draft_config = publish_config.model_copy(update={"apps": changed_apps})
        run_number = matched_ci_run_number(settings.github_repository, settings.github_sha, publish_config.ci_workflow)
        pulled = pull_build_assets(draft_config, run_number, settings.github_actor, settings.github_token)
        staged_assets = stage_draft_assets(pulled, run_number)
        ensure_draft_release(DEV_DRAFT_TAG, settings.github_repository, settings.github_sha)
        upload_draft_assets(DEV_DRAFT_TAG, settings.github_repository, staged_assets)

    pr_info = parse_merge_pr(settings.github_sha)
    section = build_prerelease_section(published, staged_assets, settings.github_repository, resolved_run_id, pr_info)
    anchor = f"run-{resolved_run_id}"
    append_draft_section(DEV_DRAFT_TAG, settings.github_repository, settings.github_sha, anchor, section)
    emit_draft_backlink(settings.github_step_summary, DEV_DRAFT_TAG, settings.github_repository, anchor)


def app_has_changes(tags: TagSource, app_name: str, app: AppConfig) -> bool:
    last_version = tags.latest_version(f"{app_name}-v")
    tag = f"{app_name}-v{last_version}" if last_version else None
    return tags.has_changes_since(tag, app.path)


def parse_merge_pr(sha: str) -> tuple[int, str] | None:
    message = bash_output(f"git log -1 --format=%B {sha}").strip()
    match = _MERGE_PR_PATTERN.search(message)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


def build_prerelease_section(
    published: list[tuple[str, str, str]],
    staged_assets: list[tuple[str, Path]],
    repository: str,
    run_id: str,
    pr_info: tuple[int, str] | None,
) -> str:
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    heading_parts = [f"[Run #{run_id}]({run_url})"]
    if pr_info is not None:
        pr_number, pr_title = pr_info
        pr_url = f"https://github.com/{repository}/pull/{pr_number}"
        heading_parts.append(f"[PR #{pr_number}: {pr_title}]({pr_url})")
    lines = [f"### {' — '.join(heading_parts)}"]

    if published:
        lines.extend(["", "| Package | Version | Registry |", "|---|---|---|"])
        for registry_name, identity, version in published:
            url = registry_url(registry_name, identity, version)
            if url is not None:
                lines.append(f"| {identity} | {version} | [{registry_name}]({url}) |")
            else:
                lines.append(f"| {identity} | {version} | {registry_name} |")

    if staged_assets:
        lines.append("")
        for name, _ in staged_assets:
            url = f"https://github.com/{repository}/releases/download/{DEV_DRAFT_TAG}/{name}"
            lines.append(f"- [{name}]({url})")

    return "\n".join(lines)
