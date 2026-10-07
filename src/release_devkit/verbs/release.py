from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output

from release_devkit.builds import pull_build_assets
from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import DEV_DRAFT_TAG, delete_draft_release
from release_devkit.plan import compute_release_plan, package_rows
from release_devkit.publishing import StableStrategy, publish_packages
from release_devkit.rendering import PackageRow, render_images_table, render_packages_table
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

    staging = Path(mkdtemp(prefix="release-assets-"))
    assets: list[Path] = []
    for artifact, source in pull_build_assets(
        publish_config.apps,
        publish_config.builds_registry,
        context.certified,
        settings.github_actor,
        settings.github_token,
    ):
        asset = staging / (artifact.name or source.name)
        shutil.copy2(source, asset)
        assets.append(asset)

    rows = package_rows(packages)

    for app_name in publish_config.apps:
        version = latest_version(f"{app_name}-v")
        if version:
            rows.append(PackageRow(app_name, version))

    notes = "\n".join(
        ["## Packages", ""]
        + render_packages_table(rows)
        + (["", "## Built images"] + render_images_table(context.manifest) if context.manifest else [])
        + [""]
    )
    print(notes)

    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(notes)
        notes_path = file.name
    bash(
        f"gh release create {release_tag} --title {release_tag}"
        f" --notes-file {notes_path}"
        f" --repo {repository}"
        f" {' '.join(f'{asset}' for asset in assets)}"
    )
    Path(notes_path).unlink()
    print(f"  Release created: {release_tag}")

    delete_draft_release(DEV_DRAFT_TAG, repository)
