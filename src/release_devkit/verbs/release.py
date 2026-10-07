from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.builds import stage_build_assets
from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import DEV_DRAFT_TAG, delete_draft_release, run_with_notes_file
from release_devkit.plan import package_rows, package_version_overrides
from release_devkit.publishing import StableStrategy, publish_changed_packages
from release_devkit.rendering import collect_app_rows, render_release_body
from release_devkit.tags import create_and_push_tag, latest_version

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    release_plan, published = publish_changed_packages(context, StableStrategy())

    if not release_plan.publishing and not release_plan.app_versions:
        return

    packages = context.publish_config.packages

    for name in packages:
        plan = release_plan.plans[name]
        if plan.publish:
            create_and_push_tag(f"{name}-v{plan.version}")

    for app_name, app_version in release_plan.app_versions.items():
        create_and_push_tag(f"{app_name}-v{app_version}")

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {context.settings.github_repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    release_tag = f"{year_month}.{(int(existing) if existing else 0) + 1}"
    staged = stage_build_assets(context, context.publish_config.apps, None)
    assets = [target for _, _, target in staged]
    app_versions = {app_name: latest_version(f"{app_name}-v") for app_name in context.publish_config.apps}
    app_rows = collect_app_rows(staged, app_versions, context.settings.github_repository, release_tag)

    rows = package_rows(packages, package_version_overrides(packages, published))

    notes = render_release_body(None, rows, app_rows, context.manifest, level=2) + "\n"
    run_with_notes_file(
        f"gh release create {release_tag} --title {release_tag} --repo {context.settings.github_repository}"
        f" {' '.join(f'{asset}' for asset in assets)}",
        notes,
    )

    delete_draft_release(DEV_DRAFT_TAG, context.settings.github_repository)
