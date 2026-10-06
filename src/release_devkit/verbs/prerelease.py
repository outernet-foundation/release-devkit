from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_check, bash_output
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from ..config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from ..builds import (
    DigestEntry,
    builds_registry_of,
    matched_ci_run_number,
    pull_digest_manifest,
    render_images_table,
)
from ..drafts import (
    DEV_DRAFT_TAG,
    append_draft_section,
    publish_draft_assets,
)
from ..outputs import append_line
from ..plan import compute_release_plan, setup_publishing_environment
from ..registries import DEV_VERSION_FORMATS, NPM_DEV_DIST_TAG, PublishRequest, build_registries, registry_url
from ..tags import GitTags

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
) -> None:
    settings = Settings.model_validate({})
    resolved_run_id = run_id or settings.github_run_id
    if not resolved_run_id.isdigit():
        raise SystemExit("dev run id must be all digits: pass --run-id or run inside CI")

    publish_config = load_config(config)
    packages = publish_config.packages
    tags = GitTags()

    run_number = ""
    integrate_run: tuple[str, str] | None = None
    new_image_manifest: dict[str, DigestEntry] = {}

    with ci_step("Compute dev publish plan"):
        release_plan = compute_release_plan(publish_config, tags)

        summary_lines = [
            "### Dev Publish Plan",
            "| Package | Publish | Versions |",
            "|---|---|---|",
        ]
        for name, package in packages.items():
            plan = release_plan.plans[name]
            if not plan.publish:
                summary_lines.append(f"| {plan.name} | False | - |")
                continue
            versions = ", ".join(
                f"{registry_name}: {identity} @ {DEV_VERSION_FORMATS[registry_name](plan.version, resolved_run_id)}"
                for registry_name, identity in package.registries.items()
            )
            summary_lines.append(f"| {plan.name} | True | {versions} |")
        summary = "\n".join(summary_lines)

        print(summary)
        append_line(settings.github_step_summary, summary)

        changed_apps: dict[str, AppConfig] = {}
        for name, app in publish_config.apps.items():
            if app.builds is None:
                continue
            last_version = tags.latest_version(f"{name}-v")
            tag = f"{name}-v{last_version}" if last_version else None
            if tags.has_changes_since(tag, app.path):
                changed_apps[name] = app

        has_package_changes = release_plan.publishing
        has_app_changes = bool(changed_apps)

        builds_registry = builds_registry_of(publish_config)
        if builds_registry is not None:
            run_number, html_url = matched_ci_run_number(
                settings.github_repository, settings.github_sha, publish_config.ci_workflow
            )
            integrate_run = (run_number, html_url)
            manifest = pull_digest_manifest(builds_registry, run_number, settings.github_actor, settings.github_token)
            if manifest is not None:
                existing_digests: set[str] = set()
                if bash_check(f"gh release view {DEV_DRAFT_TAG} --repo {settings.github_repository}"):
                    draft_body = bash_output(
                        f"gh release view {DEV_DRAFT_TAG} --repo {settings.github_repository} --json body --jq .body"
                    )
                    existing_digests = set(re.findall(r"sha256:[a-f0-9]{64}", draft_body))
                new_image_manifest = {
                    target: entry for target, entry in manifest.items() if entry.digest not in existing_digests
                }

        has_image_changes = bool(new_image_manifest)
        if not has_package_changes and not has_app_changes and not has_image_changes:
            print("Nothing to publish")
            return

        if dry_run:
            print("Dry run \u2014 skipping publish")
            return

    published: list[tuple[str, str, str]] = []
    if has_package_changes:
        setup_publishing_environment(release_plan, packages, settings.github_workspace)

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
        staged_assets = publish_draft_assets(
            draft_config,
            run_number,
            settings.github_actor,
            settings.github_token,
            DEV_DRAFT_TAG,
            settings.github_repository,
            settings.github_sha,
        )

    merge_message = bash_output(f"git log -1 --format=%B {settings.github_sha}").strip()
    merge_match = _MERGE_PR_PATTERN.search(merge_message)
    pr_info = (int(merge_match.group(1)), merge_match.group(2)) if merge_match is not None else None

    if integrate_run is not None:
        section_run_number, run_url = integrate_run
        heading_parts = [f"[Integrate run #{section_run_number}]({run_url})"]
    else:
        run_url = f"https://github.com/{settings.github_repository}/actions/runs/{resolved_run_id}"
        heading_parts = [f"[Run #{resolved_run_id}]({run_url})"]
    if pr_info is not None:
        pr_number, pr_title = pr_info
        pr_url = f"https://github.com/{settings.github_repository}/pull/{pr_number}"
        heading_parts.append(f"[PR #{pr_number}: {pr_title}]({pr_url})")
    section_lines = [f"### {' \u2014 '.join(heading_parts)}"]

    if published:
        section_lines.extend(["", "| Package | Version | Registry |", "|---|---|---|"])
        for registry_name, identity, version in published:
            url = registry_url(registry_name, identity, version)
            if url is not None:
                section_lines.append(f"| {identity} | {version} | [{registry_name}]({url}) |")
            else:
                section_lines.append(f"| {identity} | {version} | {registry_name} |")

    if staged_assets:
        section_lines.append("")
        for name, _ in staged_assets:
            url = f"https://github.com/{settings.github_repository}/releases/download/{DEV_DRAFT_TAG}/{name}"
            section_lines.append(f"- [{name}]({url})")

    if new_image_manifest:
        section_lines.append("")
        section_lines.append("#### Built images")
        section_lines.extend(render_images_table(new_image_manifest))

    section = "\n".join(section_lines)
    anchor = f"run-{resolved_run_id}"
    append_draft_section(DEV_DRAFT_TAG, settings.github_repository, anchor, section)

    draft_url = bash_output(
        f"gh release view {DEV_DRAFT_TAG} --repo {settings.github_repository} --json url --jq .url"
    ).strip()
    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft_url}#{anchor})"
    print(backlink_text)
    append_line(settings.github_step_summary, backlink_text)
