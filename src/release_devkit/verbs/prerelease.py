from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH, write_step_summary
from release_devkit.context import merge_push_context
from release_devkit.drafts import (
    DEV_DRAFT_TAG,
    DraftRelease,
    asset_stem,
    publish_draft_assets,
)
from release_devkit.plan import apps_with_changes, compute_release_plan, package_rows
from release_devkit.publishing import DevStrategy, publish_packages
from release_devkit.rendering import DraftSection, render_draft_section
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

    has_image_changes = manifest is not None and draft.has_new_digests(manifest)

    packages = publish_config.packages
    tags = GitTags()

    release_plan = compute_release_plan(publish_config, tags)

    changed_apps = apps_with_changes(publish_config, tags)

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

    identity_to_name = {
        identity: name for name, package in packages.items() for identity in package.registries.values()
    }
    dev_versions = {identity_to_name[identity]: version for _, identity, version in published}
    rows = package_rows(packages, tags, dev_versions)

    fresh_assets = draft.asset_links(staged_assets)
    replaced_stems = {stem for stem in (asset_stem(name) for name, _ in staged_assets) if stem is not None}
    carried_assets = draft.carried_asset_links(replaced_stems)
    assets = (fresh_assets + carried_assets) or None

    section = render_draft_section(
        DraftSection(
            heading_fragments=heading_fragments,
            packages=rows or None,
            assets=assets,
            images=manifest,
        )
    )
    anchor = f"sha-{short}"
    draft.upsert_section(anchor, section)

    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft.url}#{anchor})"
    print(backlink_text)
    write_step_summary(settings.github_step_summary, backlink_text)
