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
from release_devkit.plan import compute_release_plan, package_rows
from release_devkit.publishing import StableStrategy, publish_packages
from release_devkit.rendering import AppRow, render_app_table, render_images_table, render_packages_table
from release_devkit.tags import create_and_push_tag, latest_version

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)
    settings = context.settings
    publish_config = context.publish_config
    repository = settings.github_repository

    packages = publish_config.packages

    release_plan = compute_release_plan(publish_config)

    if not release_plan.anything_releases():
        print("Nothing to publish")
        return

    if packages:
        publish_packages(
            packages,
            release_plan,
            settings.nuget_api_key,
            StableStrategy(),
            settings.github_workspace,
        )

    for name in packages:
        plan = release_plan.plans[name]
        if plan.publish:
            tag = f"{name}-v{plan.version}"
            create_and_push_tag(tag)
            print(f"  Tagged: {tag}")

    for app_name, app_version in release_plan.app_versions.items():
        tag = f"{app_name}-v{app_version}"
        create_and_push_tag(tag)
        print(f"  Tagged: {tag}")

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    release_tag = f"{year_month}.{(int(existing) if existing else 0) + 1}"

    staged = stage_build_assets(context, publish_config.apps, None)
    assets = [target for _, _, target in staged]
    asset_by_app = {app_name: asset_name for app_name, asset_name, _ in staged}

    rows = package_rows(packages)

    app_rows: list[AppRow] = []
    for app_name in publish_config.apps:
        version = latest_version(f"{app_name}-v")
        if not version:
            continue
        asset_name = asset_by_app.get(app_name)
        app_rows.append(
            AppRow(
                app_name,
                version,
                asset_name,
                f"https://github.com/{repository}/releases/download/{release_tag}/{asset_name}" if asset_name else None,
            )
        )

    notes = "\n".join(
        ["## Packages", ""]
        + render_packages_table(rows)
        + (["", "## Apps"] + render_app_table(app_rows) if app_rows else [])
        + (["", "## Built images"] + render_images_table(context.manifest) if context.manifest else [])
        + [""]
    )
    print(notes)

    run_with_notes_file(
        f"gh release create {release_tag} --title {release_tag} --repo {repository} {' '.join(f'{asset}' for asset in assets)}",
        notes,
    )
    print(f"  Release created: {release_tag}")

    delete_draft_release(DEV_DRAFT_TAG, repository)
