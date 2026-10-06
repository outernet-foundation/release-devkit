from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, AppConfig, Settings, load_config, write_step_summary
from release_devkit.builds import (
    DigestEntry,
    builds_registry_of,
    matched_ci_run_number,
    pull_digest_manifest,
)
from release_devkit.drafts import (
    DEV_DRAFT_TAG,
    append_draft_section,
    publish_draft_assets,
)
from release_devkit.plan import compute_release_plan, setup_publishing_environment
from release_devkit.publishing import DevStrategy, publish_packages
from release_devkit.registries import DEV_VERSION_FORMATS, registry_url
from release_devkit.rendering import AssetLink, DraftSection, PackageRow, RegistryLink, render_draft_section
from release_devkit.tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


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
        write_step_summary(settings.github_step_summary, summary)

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
        published = publish_packages(packages, release_plan, settings.nuget_api_key, DevStrategy(resolved_run_id))

        if published:
            recap = "\n".join([
                "### Published dev versions",
                *(f"{registry_name}: {identity} @ {version}" for registry_name, identity, version in published),
            ])
            print(recap)
            print("Consume these by exact version pin - there is no discovery tooling by design")
            write_step_summary(settings.github_step_summary, recap)

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

    heading_fragments: list[str] = []
    if integrate_run is not None:
        section_run_number, run_url = integrate_run
        heading_fragments.append(f"[Integrate run #{section_run_number}]({run_url})")
    else:
        run_url = f"https://github.com/{settings.github_repository}/actions/runs/{resolved_run_id}"
        heading_fragments.append(f"[Run #{resolved_run_id}]({run_url})")
    if pr_info is not None:
        pr_number, pr_title = pr_info
        pr_url = f"https://github.com/{settings.github_repository}/pull/{pr_number}"
        heading_fragments.append(f"[PR #{pr_number}: {pr_title}]({pr_url})")

    package_rows: list[PackageRow] | None = None
    if published:
        published_map = {(rn, ident): v for rn, ident, v in published}
        package_rows = []
        for name, package in publish_config.packages.items():
            plan = release_plan.plans[name]
            if not plan.publish:
                continue
            registries = [
                RegistryLink(
                    registry_name,
                    published_map[(registry_name, identity)],
                    registry_url(registry_name, identity, published_map[(registry_name, identity)]),
                )
                for registry_name, identity in package.registries.items()
            ]
            package_rows.append(PackageRow(name, plan.version, registries))

    assets = [
        AssetLink(name, f"https://github.com/{settings.github_repository}/releases/download/{DEV_DRAFT_TAG}/{name}")
        for name, _ in staged_assets
    ] or None

    section = render_draft_section(
        DraftSection(
            heading_fragments=heading_fragments,
            packages=package_rows,
            assets=assets,
            images=new_image_manifest or None,
        )
    )
    anchor = f"run-{resolved_run_id}"
    append_draft_section(DEV_DRAFT_TAG, settings.github_repository, anchor, section)

    draft_url = bash_output(
        f"gh release view {DEV_DRAFT_TAG} --repo {settings.github_repository} --json url --jq .url"
    ).strip()
    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft_url}#{anchor})"
    print(backlink_text)
    write_step_summary(settings.github_step_summary, backlink_text)
