from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output
from pydantic_settings import BaseSettings
from ci_devkit.builds import pull_build
from ci_devkit.ci_step import ci_step

from .config import BuildArtifactConfig, PublishConfig, load_config
from .registries import registry_url
from .tags import GitTags
from .plan import UNCHANGED_FALLBACK_VERSION

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

    assets = collect_build_assets(publish_config, settings)

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
                lines.append(f"| {app_name} | {version} | — |")

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


def collect_build_assets(publish_config: PublishConfig, settings: Settings) -> list[Path]:
    run_number = matched_ci_run_number(settings.github_repository, settings.github_sha, publish_config.ci_workflow)
    pulled = pull_build_assets(publish_config, run_number, settings.github_actor, settings.github_token)
    staging = Path(mkdtemp(prefix="release-assets-"))
    assets: list[Path] = []
    for artifact, source in pulled:
        asset_name = artifact.name or source.name
        asset = staging / asset_name
        shutil.copy2(source, asset)
        assets.append(asset)
    return assets


def matched_ci_run_number(repository: str, sha: str, ci_workflow: str) -> str:
    with ci_step("Find successful CI run"):
        parent = bash_output(f'gh api "/repos/{repository}/git/commits/{sha}" --jq ".parents[1].sha // .sha"').strip()
        run_number = bash_output(
            f'gh api "/repos/{repository}/actions/workflows/{ci_workflow}/runs'
            f'?head_sha={parent}&status=success" --jq ".workflow_runs[0].run_number // empty"'
        ).strip()

        if not run_number:
            print(f"::error::No successful CI run found for SHA {parent}. Cannot release untested code.")
            raise typer.Exit(code=1)

        print(f"  CI run number: {run_number}")
        return run_number


def pull_build_assets(
    publish_config: PublishConfig, run_number: str, registry_username: str, registry_token: str
) -> list[tuple[BuildArtifactConfig, Path]]:
    apps_with_builds = {name: app.builds for name, app in publish_config.apps.items() if app.builds is not None}
    if not apps_with_builds:
        return []

    build_tag = f"run-{run_number}"
    staging = Path(mkdtemp(prefix="release-builds-"))
    assets: list[tuple[BuildArtifactConfig, Path]] = []

    for app_name, builds in apps_with_builds.items():
        with ci_step(f"Pull build artifacts ({app_name})"):
            for artifact in builds.artifacts:
                target = staging / f"{artifact.project}-{artifact.platform}"
                pull_build(
                    builds.registry,
                    artifact.project,
                    artifact.platform,
                    build_tag,
                    target,
                    registry_username=registry_username,
                    registry_token=registry_token,
                )
                source = select_artifact_file(artifact, target)
                assets.append((artifact, source))
                print(f"  Asset: {source.name}")

    return assets


def select_artifact_file(artifact: BuildArtifactConfig, target: Path) -> Path:
    files = sorted(path for path in target.rglob("*") if path.is_file())
    if artifact.file is not None:
        for path in files:
            if path.name == artifact.file:
                return path
        raise SystemExit(f"Build artifact layer '{artifact.file}' not found under {target}")
    if len(files) == 1:
        return files[0]
    raise SystemExit(
        f"Build artifact for ({artifact.project}, {artifact.platform}) pulled multiple files "
        f"({', '.join(path.name for path in files)}); declare which one with 'file'"
    )
