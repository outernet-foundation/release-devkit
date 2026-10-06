from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings

from ..config import DEFAULT_CONFIG_PATH, load_config
from ..builds import (
    DigestEntry,
    builds_registry_of,
    pull_build_assets,
    pull_digest_manifest,
    render_images_table,
)
from ..outputs import append_line
from ..drafts import (
    append_draft_section,
    ensure_draft_release,
    stage_draft_assets,
    upload_draft_assets,
)

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"


class Settings(BaseSettings):
    github_repository: str
    github_sha: str = ""
    github_actor: str = ""
    github_token: str = ""
    github_run_id: str = ""
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
    manifest = pull_digest_manifest(
        builds_registry_of(publish_config), resolved_run_number, settings.github_actor, settings.github_token
    )
    ensure_draft_release(tag, settings.github_repository, settings.github_sha)
    upload_draft_assets(tag, settings.github_repository, staged)
    run_url = f"https://github.com/{settings.github_repository}/actions/runs/{settings.github_run_id}"
    section = build_draft_section(
        settings.github_repository, tag, resolved_run_number, run_url, pr_number, staged, manifest or {}
    )
    append_draft_section(tag, settings.github_repository, f"run-{resolved_run_number}", section)
    emit_draft_summary(settings.github_step_summary, tag, settings.github_repository, staged)


def build_draft_section(
    repository: str,
    tag: str,
    run_number: str,
    run_url: str,
    pr_number: int,
    staged: list[tuple[str, Path]],
    image_manifest: dict[str, DigestEntry],
) -> str:
    pr_url = f"https://github.com/{repository}/pull/{pr_number}"
    lines = [f"### [Run #{run_number}]({run_url}) — [PR #{pr_number}]({pr_url})"]
    if image_manifest:
        lines.append("")
        lines.append("#### Built images")
        lines.extend(render_images_table(image_manifest))
    if staged:
        lines.append("")
        for name, _ in staged:
            url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
            lines.append(f"- [{name}]({url})")
    return "\n".join(lines)


def emit_draft_summary(summary_path: str | None, tag: str, repository: str, staged: list[tuple[str, Path]]) -> None:
    lines = [f"### Draft release `{tag}`", ""]
    for name, _ in staged:
        url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
        lines.append(f"- [{name}]({url})")
    summary = "\n".join(lines)
    print(summary)
    append_line(summary_path, summary)
