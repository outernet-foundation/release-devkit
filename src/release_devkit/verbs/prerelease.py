from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.builds import DigestEntry
from release_devkit.config import DEFAULT_CONFIG_PATH, write_step_summary
from release_devkit.context import merge_push_context
from release_devkit.drafts import (
    DEV_DRAFT_TAG,
    DraftRelease,
    publish_draft_assets,
)
from release_devkit.plan import compute_release_plan
from release_devkit.publishing import DevStrategy, publish_packages
from release_devkit.registries import registry_url
from release_devkit.rendering import AssetLink, DraftSection, PackageRow, RegistryLink, render_draft_section
from release_devkit.tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)
    settings = context.settings
    publish_config = context.publish_config
    head = context.head
    certified = context.certified
    short = context.short
    commit_url = context.commit_url
    repository = settings.github_repository
    manifest = context.manifest

    draft = DraftRelease(DEV_DRAFT_TAG, repository, head)

    new_image_manifest: dict[str, DigestEntry] = {}
    if manifest is not None:
        existing_digests = draft.existing_digests()
        new_image_manifest = {
            target: entry for target, entry in manifest.items() if entry.digest not in existing_digests
        }
    has_image_changes = bool(new_image_manifest)

    packages = publish_config.packages
    tags = GitTags()

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

    has_app_changes = bool(changed_apps)

    if not release_plan.publishing and not has_app_changes and not has_image_changes:
        print("Nothing to publish")
        return

    published: list[tuple[str, str, str]] = []
    if release_plan.publishing:
        published = publish_packages(
            packages,
            release_plan,
            settings.nuget_api_key,
            DevStrategy(short),
            settings.github_workspace,
        )

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
            certified,
            settings.github_actor,
            settings.github_token,
            draft,
        )

    merge_message = bash_output(f"git log -1 --format=%B {head}").strip()
    merge_match = _MERGE_PR_PATTERN.search(merge_message)
    pr_info = (int(merge_match.group(1)), merge_match.group(2)) if merge_match is not None else None

    heading_fragments: list[str] = [f"[{short}]({commit_url})"]
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
    anchor = f"sha-{short}"
    draft.upsert_section(anchor, section)

    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft.url}#{anchor})"
    print(backlink_text)
    write_step_summary(settings.github_step_summary, backlink_text)
