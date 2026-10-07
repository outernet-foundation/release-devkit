from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import pr_head_context
from release_devkit.drafts import (
    DraftRelease,
    publish_draft_assets,
)
from release_devkit.plan import apps_with_changes

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
PR_REF_PATTERN = re.compile(r"^refs/pull/(\d+)/merge$")


@update_pr_app.command()
def update_pr_draft(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = pr_head_context(config)
    settings = context.settings
    publish_config = context.publish_config
    pr_number = int(PR_REF_PATTERN.findall(settings.github_ref)[0][0])
    repository = settings.github_repository
    manifest = context.manifest

    draft = DraftRelease(f"{PR_DRAFT_TAG_PREFIX}{pr_number}", repository, context.head)

    if not bool(apps_with_changes(publish_config)) and not (manifest is not None and draft.has_new_digests(manifest)):
        print("Nothing to publish")
        return

    draft.upsert_section(
        f"sha-{context.short}",
        [
            f"[{context.short}]({context.commit_url})",
            f"[PR #{pr_number}](https://github.com/{repository}/pull/{pr_number})",
        ],
        draft.asset_links(
            publish_draft_assets(
                publish_config,
                context.certified,
                settings.github_actor,
                settings.github_token,
                draft,
            )
        )
        or None,
        manifest,
    )
