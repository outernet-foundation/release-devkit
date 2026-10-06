from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, Settings, load_config
from release_devkit.drafts import DEV_DRAFT_TAG, delete_draft_release
from release_devkit.plan import UNCHANGED_FALLBACK_VERSION, compute_and_print_plan, setup_publishing_environment
from release_devkit.publishing import StableStrategy, publish_packages
from release_devkit.registries import registry_url
from release_devkit.rendering import PackageRow, RegistryLink, render_release_body
from release_devkit.tags import GitTags
from release_devkit.builds import (
    builds_registry_of,
    matched_ci_run_number,
    pull_build_assets,
    pull_digest_manifest,
)

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    packages = publish_config.packages
    tags = GitTags()

    with ci_step("Compute publish plan"):
        release_plan = compute_and_print_plan(publish_config, tags, settings.github_step_summary)

    if not release_plan.anything_releases():
        print("Nothing to publish")
        return

    setup_publishing_environment(release_plan, packages, settings.github_workspace)

    if packages:
        publish_packages(packages, release_plan, settings.nuget_api_key, StableStrategy())

    with ci_step("Create version tags"):
        for name in packages:
            plan = release_plan.plans[name]
            if plan.publish:
                tag = f"{name}-v{plan.version}"
                tags.create_and_push_tag(tag)
                print(f"  Tagged: {tag}")

        for app_name, app_version in release_plan.app_versions.items():
            tag = f"{app_name}-v{app_version}"
            tags.create_and_push_tag(tag)
            print(f"  Tagged: {tag}")

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {settings.github_repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    count = int(existing) if existing else 0
    release_tag = f"{year_month}.{count + 1}"

    run_number, _ = matched_ci_run_number(settings.github_repository, settings.github_sha, publish_config.ci_workflow)
    pulled = pull_build_assets(publish_config, run_number, settings.github_actor, settings.github_token)
    staging = Path(mkdtemp(prefix="release-assets-"))
    assets: list[Path] = []
    for artifact, source in pulled:
        asset_name = artifact.name or source.name
        asset = staging / asset_name
        shutil.copy2(source, asset)
        assets.append(asset)

    manifest = pull_digest_manifest(
        builds_registry_of(publish_config), run_number, settings.github_actor, settings.github_token
    )

    with ci_step("Create GitHub Release"):
        rows: list[PackageRow] = []
        for name, package in publish_config.packages.items():
            version = tags.latest_version(f"{name}-v") or UNCHANGED_FALLBACK_VERSION
            registries = [
                RegistryLink(
                    registry_name,
                    version,
                    registry_url(registry_name, identity, version) if version != UNCHANGED_FALLBACK_VERSION else None,
                )
                for registry_name, identity in package.registries.items()
            ]
            rows.append(PackageRow(name, version, registries))

        for app_name in publish_config.apps:
            version = tags.latest_version(f"{app_name}-v")
            if version:
                rows.append(PackageRow(app_name, version))

        notes = render_release_body(rows, manifest)
        print(notes)

        asset_args = " ".join(f'"{asset}"' for asset in assets)
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
            file.write(notes)
            notes_path = file.name
        bash(
            f"gh release create {release_tag} --title {release_tag}"
            f" --notes-file {notes_path}"
            f" --repo {settings.github_repository}"
            f" {asset_args}"
        )
        Path(notes_path).unlink()
        print(f"  Release created: {release_tag}")

    delete_draft_release(DEV_DRAFT_TAG, settings.github_repository)
