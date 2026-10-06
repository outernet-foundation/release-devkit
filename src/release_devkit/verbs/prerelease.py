from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, Settings, load_config, write_step_summary
from release_devkit.builds import (
    DigestEntry,
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
from release_devkit.registries import registry_url
from release_devkit.rendering import AssetLink, DraftSection, PackageRow, RegistryLink, render_draft_section
from release_devkit.tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    repository: Annotated[str, typer.Option(help="GitHub repository (owner/repo)")],
    sha: Annotated[str, typer.Option(help="Commit SHA being released")],
    actor: Annotated[str, typer.Option(help="GitHub actor for registry auth")],
    workspace: Annotated[str, typer.Option(help="GitHub workspace path")],
    run_id: Annotated[int, typer.Option(help="CI run id baked into every dev version")],
    step_summary: Annotated[str | None, typer.Option(help="Path to $GITHUB_STEP_SUMMARY file")] = None,
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    packages = publish_config.packages
    tags = GitTags()

    run_number = ""
    integrate_run: tuple[str, str] | None = None
    new_image_manifest: dict[str, DigestEntry] = {}

    with ci_step("Compute dev publish plan"):
        release_plan = compute_release_plan(publish_config, tags)

        changed_apps = {
            name: app
            for name, app in publish_config.apps.items()
            if app.builds is not None
            and tags.has_changes_since(
                f"{name}-v{v}" if (v := tags.latest_version(f"{name}-v")) else None,
                app.path,
            )
        }

        has_package_changes = release_plan.publishing
        has_app_changes = bool(changed_apps)

        builds_registry = publish_config.builds_registry
        if builds_registry is not None:
            run_number, html_url = matched_ci_run_number(repository, sha, publish_config.ci_workflow)
            integrate_run = (run_number, html_url)
            manifest = pull_digest_manifest(builds_registry, run_number, actor, settings.github_token)
            if manifest is not None:
                existing_digests: set[str] = set()
                if bash_check(f"gh release view {DEV_DRAFT_TAG} --repo {repository}"):
                    draft_body = bash_output(
                        f"gh release view {DEV_DRAFT_TAG} --repo {repository} --json body --jq .body"
                    )
                    existing_digests = set(re.findall(r"sha256:[a-f0-9]{64}", draft_body))
                new_image_manifest = {
                    target: entry for target, entry in manifest.items() if entry.digest not in existing_digests
                }

        has_image_changes = bool(new_image_manifest)
        if not has_package_changes and not has_app_changes and not has_image_changes:
            print("Nothing to publish")
            return

    published: list[tuple[str, str, str]] = []
    if has_package_changes:
        setup_publishing_environment(release_plan, packages, workspace)
        published = publish_packages(packages, release_plan, settings.nuget_api_key, DevStrategy(run_id))

        if published:
            recap = "\n".join([
                "### Published dev versions",
                *(f"{registry_name}: {identity} @ {version}" for registry_name, identity, version in published),
            ])
            print(recap)
            print("Consume these by exact version pin - there is no discovery tooling by design")
            write_step_summary(step_summary, recap)

    staged_assets: list[tuple[str, Path]] = []
    if has_app_changes:
        draft_config = publish_config.model_copy(update={"apps": changed_apps})
        staged_assets = publish_draft_assets(
            draft_config,
            run_number,
            actor,
            settings.github_token,
            DEV_DRAFT_TAG,
            repository,
            sha,
        )

    merge_message = bash_output(f"git log -1 --format=%B {sha}").strip()
    merge_match = _MERGE_PR_PATTERN.search(merge_message)
    pr_info = (int(merge_match.group(1)), merge_match.group(2)) if merge_match is not None else None

    heading_fragments: list[str] = []
    if integrate_run is not None:
        section_run_number, run_url = integrate_run
        heading_fragments.append(f"[Integrate run #{section_run_number}]({run_url})")
    else:
        run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
        heading_fragments.append(f"[Run #{run_id}]({run_url})")
    if pr_info is not None:
        pr_number, pr_title = pr_info
        pr_url = f"https://github.com/{repository}/pull/{pr_number}"
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
        AssetLink(name, f"https://github.com/{repository}/releases/download/{DEV_DRAFT_TAG}/{name}")
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
    anchor = f"run-{run_id}"
    append_draft_section(DEV_DRAFT_TAG, repository, anchor, section)

    draft_url = bash_output(f"gh release view {DEV_DRAFT_TAG} --repo {repository} --json url --jq .url").strip()
    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft_url}#{anchor})"
    print(backlink_text)
    write_step_summary(step_summary, backlink_text)
