from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import DEV_DRAFT_TAG, write_draft_section
from release_devkit.plan import compute_release_plan, package_rows
from release_devkit.publishing import DevStrategy, publish_packages

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    packages = context.publish_config.packages

    release_plan = compute_release_plan(context.publish_config)

    published: list[tuple[str, str, str]] = []
    if release_plan.publishing:
        published = publish_packages(
            packages,
            release_plan,
            context.settings.nuget_api_key,
            DevStrategy(context.short),
            context.settings.github_workspace,
        )

    groups = _MERGE_PR_PATTERN.findall(bash_output(f"git log -1 --format=%B {context.head}").strip())[0]
    pr_number = int(groups[0])

    write_draft_section(
        context,
        DEV_DRAFT_TAG,
        [
            f"[{context.short}]({context.commit_url})",
            f"[PR #{pr_number}: {groups[1]}](https://github.com/{context.settings.github_repository}/pull/{pr_number})",
        ],
        stage_changed_only=True,
        publishing=bool(release_plan.publishing),
        packages=package_rows(
            packages,
            {
                {identity: name for name, package in packages.items() for identity in package.registries.values()}[
                    identity
                ]: version
                for _, identity, version in published
            },
        ),
    )
