from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import pr_head_context
from release_devkit.drafts import write_draft_section

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
PR_REF_PATTERN = re.compile(r"^refs/pull/(\d+)/merge$")


@update_pr_app.command()
def update_pr_draft(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = pr_head_context(config)

    write_draft_section(
        context,
        f"{PR_DRAFT_TAG_PREFIX}{int(PR_REF_PATTERN.findall(context.settings.github_ref)[0][0])}",
        [f"[{context.short}]({context.commit_url})"],
    )
