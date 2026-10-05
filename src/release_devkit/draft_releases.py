from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_check
from ci_devkit.ci_step import ci_step
from pydantic_settings import BaseSettings

from .config import DEFAULT_CONFIG_PATH, BuildArtifactConfig, load_config
from .create_release import pull_build_assets
from .outputs import append_line

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
DEV_DRAFT_TAG = "dev-builds"


class Settings(BaseSettings):
    github_repository: str
    github_sha: str = ""
    github_actor: str = ""
    github_token: str = ""
    github_step_summary: str | None = None


@update_pr_app.command()
def update_pr_draft(
    pr_number: Annotated[int, typer.Option(help="PR number whose draft to update")],
    run_number: Annotated[int, typer.Option(help="CI run number whose builds to surface")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    if not any(app.builds for app in publish_config.apps.values()):
        return

    tag = f"{PR_DRAFT_TAG_PREFIX}{pr_number}"
    resolved_run_number = str(run_number)
    pulled = pull_build_assets(publish_config, resolved_run_number, settings.github_actor, settings.github_token)
    staged = stage_draft_assets(pulled, resolved_run_number)
    ensure_draft_release(tag, settings.github_repository, settings.github_sha)
    upload_draft_assets(tag, settings.github_repository, staged)
    emit_draft_summary(settings.github_step_summary, tag, settings.github_repository, staged)


def stage_draft_assets(assets: list[tuple[BuildArtifactConfig, Path]], run_number: str) -> list[tuple[str, Path]]:
    staging = Path(mkdtemp(prefix="draft-assets-"))
    staged: list[tuple[str, Path]] = []
    for artifact, source in assets:
        if artifact.name is not None:
            configured = Path(artifact.name)
            stem = configured.stem
            suffix = configured.suffix
        else:
            stem = source.stem
            suffix = source.suffix
        name = f"{stem}-run-{run_number}{suffix}"
        target = staging / name
        shutil.copy2(source, target)
        staged.append((name, target))
        print(f"  Asset: {name}")
    return staged


def ensure_draft_release(tag: str, repository: str, sha: str) -> None:
    with ci_step(f"Ensure draft release {tag}"):
        if bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} already exists")
            return
        bash(f"gh release create {tag} --draft --target {sha} --title {tag} --notes '' --repo {repository}")
        print(f"  Draft release {tag} created")


def upload_draft_assets(tag: str, repository: str, staged: list[tuple[str, Path]]) -> None:
    with ci_step(f"Upload assets to {tag}"):
        files = " ".join(f'"{path}"' for _, path in staged)
        bash(f"gh release upload {tag} {files} --clobber --repo {repository}")


def emit_draft_summary(summary_path: str | None, tag: str, repository: str, staged: list[tuple[str, Path]]) -> None:
    lines = [f"### Draft release `{tag}`", ""]
    for name, _ in staged:
        url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
        lines.append(f"- [{name}]({url})")
    summary = "\n".join(lines)
    print(summary)
    append_line(summary_path, summary)


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")
