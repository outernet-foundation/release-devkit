from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH, write_step_summary
from release_devkit.context import pr_head_context
from release_devkit.drafts import (
    DraftRelease,
    publish_draft_assets,
)
from release_devkit.plan import apps_with_changes
from release_devkit.rendering import DraftSection, render_asset_links, render_draft_section
from release_devkit.tags import GitTags

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
PR_REF_PATTERN = re.compile(r"^refs/pull/(\d+)/merge$")


@update_pr_app.command()
def update_pr_draft(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = pr_head_context(config)
    settings = context.settings
    repository = settings.github_repository
    pr_number = pr_number_from_ref(settings.github_ref)
    certified = context.certified

    if not any(app.builds for app in context.publish_config.apps.values()):
        return

    tag = f"{PR_DRAFT_TAG_PREFIX}{pr_number}"
    draft = DraftRelease(tag, repository, certified)

    has_app_changes = bool(apps_with_changes(context.publish_config, GitTags()))
    has_image_changes = context.manifest is not None and draft.has_new_digests(context.manifest)
    if not has_app_changes and not has_image_changes:
        print("Nothing to publish")
        return

    staged = publish_draft_assets(
        context.publish_config,
        certified,
        settings.github_actor,
        settings.github_token,
        draft,
    )

    pr_url = f"https://github.com/{repository}/pull/{pr_number}"

    assets = draft.asset_links(staged)

    section = render_draft_section(
        DraftSection(
            heading_fragments=[
                f"[{context.short}]({context.commit_url})",
                f"[PR #{pr_number}]({pr_url})",
            ],
            assets=assets or None,
            images=context.manifest,
        )
    )

    draft.upsert_section(f"sha-{context.short}", section)

    summary_lines = [f"### Draft release `{tag}`", ""]
    summary_lines.extend(render_asset_links(assets))
    summary = "\n".join(summary_lines)
    print(summary)
    write_step_summary(settings.github_step_summary, summary)


def pr_number_from_ref(ref: str) -> int:
    match = PR_REF_PATTERN.fullmatch(ref)
    if match is None:
        raise SystemExit(f"GITHUB_REF {ref!r} is not a pull_request ref — this verb runs on pull_request events")
    return int(match.group(1))
