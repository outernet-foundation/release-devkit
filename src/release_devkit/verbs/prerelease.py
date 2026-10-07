from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import DEV_DRAFT_TAG, write_draft_section
from release_devkit.plan import package_rows, package_version_overrides
from release_devkit.publishing import DevStrategy, publish_changed_packages

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    _, published = publish_changed_packages(context, DevStrategy(context.short))

    packages = context.publish_config.packages

    pr_number, pr_title = _MERGE_PR_PATTERN.findall(bash_output(f"git log -1 --format=%B {context.head}").strip())[0]

    write_draft_section(
        context,
        DEV_DRAFT_TAG,
        [
            f"[{context.short}]({context.commit_url})",
            f"[PR #{pr_number}: {pr_title}](https://github.com/{context.settings.github_repository}/pull/{pr_number})",
        ],
        packages=package_rows(packages, package_version_overrides(packages, published)),
    )
