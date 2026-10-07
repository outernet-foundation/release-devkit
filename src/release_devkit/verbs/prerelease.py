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
from release_devkit.rendering import render_draft_section

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
    short = context.short
    repository = settings.github_repository
    manifest = context.manifest

    packages = publish_config.packages

    release_plan = compute_release_plan(publish_config)

    draft = DraftRelease(DEV_DRAFT_TAG, repository, head)

    changed_apps = apps_with_changes(publish_config)

    has_app_changes = bool(changed_apps)

    if (
        not release_plan.publishing
        and not has_app_changes
        and not (manifest is not None and draft.has_new_digests(manifest))
    ):
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

    merge_match = _MERGE_PR_PATTERN.search(bash_output(f"git log -1 --format=%B {head}").strip())

    pr_number = int(merge_match.group(1))
    heading_fragments: list[str] = [
        f"[{short}]({context.commit_url})",
        f"[PR #{pr_number}: {merge_match.group(2)}](https://github.com/{repository}/pull/{pr_number})",
    ]

    staged_assets: list[tuple[str, Path]] = []
    if has_app_changes:
        staged_assets = publish_draft_assets(
            publish_config.model_copy(update={"apps": changed_apps}),
            context.certified,
            settings.github_actor,
            settings.github_token,
            draft,
        )

    anchor = f"sha-{short}"
    draft.upsert_section(
        anchor,
        render_draft_section(
            heading_fragments=heading_fragments,
            packages=package_rows(
                packages,
                {
                    {identity: name for name, package in packages.items() for identity in package.registries.values()}[
                        identity
                    ]: version
                    for _, identity, version in published
                },
            )
            or None,
            assets=(
                draft.asset_links(staged_assets)
                + draft.carried_asset_links({
                    stem for stem in (asset_stem(name) for name, _ in staged_assets) if stem is not None
                })
            )
            or None,
            images=manifest,
        ),
    )

    backlink_text = f"### Draft release `{DEV_DRAFT_TAG}` updated\n- [Section `{anchor}`]({draft.url}#{anchor})"
    print(backlink_text)
    write_step_summary(settings.github_step_summary, backlink_text)
