from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import pr_head_context
from release_devkit.drafts import write_release
from release_devkit.tags import latest_version

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@update_pr_app.command()
def update_pr_draft(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = pr_head_context(config)

    write_release(
        context,
        f"pr-{re.findall(r'^refs/pull/(\d+)/merge$', context.settings.github_ref)[0][0]}",
        context.short,
        {name: latest_version(f"{name}-v") for name in context.publish_config.apps},
        f"### [{context.short}]({context.commit_url})",
        None,
        publish=False,
    )
