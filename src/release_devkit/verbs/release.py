from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import (
    DEV_DRAFT_TAG,
    delete_draft_release,
    edit_release_notes,
    ensure_draft_release,
    latest_app_versions,
    stage_and_upload,
)
from release_devkit.plan import package_rows, package_version_overrides
from release_devkit.publishing import publish_packages
from release_devkit.rendering import collect_app_rows, render_release_body
from release_devkit.tags import create_and_push_tag

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    release_plan, published = publish_packages(context, dev=False)

    if not release_plan.publishing and not release_plan.app_versions:
        return

    packages = context.publish_config.packages

    for app_name, app_version in release_plan.app_versions.items():
        create_and_push_tag(f"{app_name}-v{app_version}")

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {context.settings.github_repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    release_tag = f"{year_month}.{(int(existing) if existing else 0) + 1}"

    ensure_draft_release(context, release_tag)
    staged = stage_and_upload(context, release_tag, None)

    edit_release_notes(
        context,
        release_tag,
        render_release_body(
            None,
            package_rows(packages, package_version_overrides(packages, published)),
            collect_app_rows(staged, latest_app_versions(context), context.settings.github_repository, release_tag),
            context.manifest,
            level=2,
        ),
        publish=True,
    )

    delete_draft_release(DEV_DRAFT_TAG, context.settings.github_repository)
