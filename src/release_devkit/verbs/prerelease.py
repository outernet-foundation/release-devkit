from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import DEV_DRAFT_TAG, write_release
from release_devkit.publishing import publish_packages

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    release_plan, published = publish_packages(context, dev=True)

    pr_number, pr_title = re.findall(
        r"Merge PR #(\d+): (.+)", bash_output(f"git log -1 --format=%B {context.head}").strip()
    )[0]

    write_release(
        context,
        DEV_DRAFT_TAG,
        release_plan.app_last_versions,
        f"### [{context.short}]({context.commit_url})"
        f" — [PR #{pr_number}: {pr_title}](https://github.com/{context.settings.github_repository}/pull/{pr_number})",
        published,
        publish=False,
    )
