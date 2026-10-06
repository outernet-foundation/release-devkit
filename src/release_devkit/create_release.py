from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from .config import PublishConfig, load_config
from .registries import registry_url
from .tags import GitTags
from .plan import UNCHANGED_FALLBACK_VERSION
from .builds import (
    builds_registry_of,
    matched_ci_run_number,
    pull_build_assets,
    pull_digest_manifest,
    render_images_table,
)

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_repository: str
    github_sha: str
    github_actor: str = ""
    github_token: str = ""


@app.command()
def run_create_release(config: Annotated[Path, typer.Option(help="Publish configuration YAML")]) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {settings.github_repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    count = int(existing) if existing else 0
    tag = f"{year_month}.{count + 1}"

    assets, run_number = collect_build_assets(publish_config, settings)
    manifest = pull_digest_manifest(
        builds_registry_of(publish_config), run_number, settings.github_actor, settings.github_token
    )

    with ci_step("Create GitHub Release"):
        tags = GitTags()
        lines: list[str] = []

        lines.extend(["## Packages", "", "| Package | Version | Registry |", "|---|---|---|"])
        for name, package in publish_config.packages.items():
            version = tags.latest_version(f"{name}-v") or UNCHANGED_FALLBACK_VERSION
            links: list[str] = []
            for registry_name, identity in package.registries.items():
                url = registry_url(registry_name, identity, version)
                if url is not None and version != UNCHANGED_FALLBACK_VERSION:
                    links.append(f"[{registry_name}]({url})")
                else:
                    links.append(registry_name)
            lines.append(f"| {name} | {version} | {', '.join(links)} |")

        for app_name in publish_config.apps:
            version = tags.latest_version(f"{app_name}-v")
            if version:
                lines.append(f"| {app_name} | {version} | \u2014 |")

        if manifest:
            lines.append("")
            lines.append("## Built images")
            lines.extend(render_images_table(manifest))

        lines.append("")
        notes = "\n".join(lines)
        print(notes)

        asset_args = " ".join(f'"{asset}"' for asset in assets)
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
            file.write(notes)
            notes_path = file.name
        bash(
            f"gh release create {tag} --title {tag}"
            f" --notes-file {notes_path}"
            f" --repo {settings.github_repository}"
            f" {asset_args}"
        )
        Path(notes_path).unlink()
        print(f"  Release created: {tag}")


def collect_build_assets(publish_config: PublishConfig, settings: Settings) -> tuple[list[Path], str]:
    run_number, _ = matched_ci_run_number(settings.github_repository, settings.github_sha, publish_config.ci_workflow)
    pulled = pull_build_assets(publish_config, run_number, settings.github_actor, settings.github_token)
    staging = Path(mkdtemp(prefix="release-assets-"))
    assets: list[Path] = []
    for artifact, source in pulled:
        asset_name = artifact.name or source.name
        asset = staging / asset_name
        shutil.copy2(source, asset)
        assets.append(asset)
    return assets, run_number
