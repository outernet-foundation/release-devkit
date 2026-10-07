from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import pr_head_context
from release_devkit.drafts import (
    edit_release_notes,
    ensure_draft_release,
    stage_and_upload,
    upsert_section,
)
from release_devkit.rendering import collect_app_rows, render_release_body
from release_devkit.tags import latest_version

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
PR_REF_PATTERN = re.compile(r"^refs/pull/(\d+)/merge$")


@update_pr_app.command()
def update_pr_draft(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = pr_head_context(config)

    tag = f"{PR_DRAFT_TAG_PREFIX}{PR_REF_PATTERN.findall(context.settings.github_ref)[0][0]}"

    app_last_versions = {name: latest_version(f"{name}-v") for name in context.publish_config.apps}

    body = ensure_draft_release(context, tag)

    staged = stage_and_upload(context, tag, context.short)

    app_rows = collect_app_rows(staged, app_last_versions, context.settings.github_repository, tag)

    body = upsert_section(
        body,
        f"sha-{context.short}",
        render_release_body(f"### [{context.short}]({context.commit_url})", None, app_rows, context.manifest, level=4),
    )

    edit_release_notes(context, tag, body, publish=False)
