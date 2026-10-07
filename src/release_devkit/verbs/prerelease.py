from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import (
    DEV_DRAFT_TAG,
    edit_release_notes,
    ensure_draft_release,
    stage_and_upload,
    upsert_section,
)
from release_devkit.plan import package_rows, package_version_overrides
from release_devkit.publishing import publish_packages
from release_devkit.rendering import collect_app_rows, render_release_body

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    release_plan, published = publish_packages(context, dev=True)

    packages = context.publish_config.packages

    pr_number, pr_title = _MERGE_PR_PATTERN.findall(bash_output(f"git log -1 --format=%B {context.head}").strip())[0]

    body = ensure_draft_release(context, DEV_DRAFT_TAG)

    staged = stage_and_upload(context, DEV_DRAFT_TAG, context.short)

    app_rows = collect_app_rows(
        staged, release_plan.app_last_versions, context.settings.github_repository, DEV_DRAFT_TAG
    )

    body = upsert_section(
        body,
        f"sha-{context.short}",
        render_release_body(
            f"### [{context.short}]({context.commit_url})"
            f" — [PR #{pr_number}: {pr_title}](https://github.com/{context.settings.github_repository}/pull/{pr_number})",
            package_rows(packages, package_version_overrides(packages, published)),
            app_rows,
            context.manifest,
            level=4,
        ),
    )

    edit_release_notes(context, DEV_DRAFT_TAG, body, publish=False)
