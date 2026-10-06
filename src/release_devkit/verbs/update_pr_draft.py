from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH, Settings, load_config, write_step_summary
from release_devkit.builds import (
    pull_digest_manifest,
)
from release_devkit.drafts import (
    append_draft_section,
    publish_draft_assets,
)
from release_devkit.rendering import AssetLink, DraftSection, render_asset_links, render_draft_section

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"


@update_pr_app.command()
def update_pr_draft(
    pr_number: Annotated[int, typer.Option(help="PR number whose draft to update")],
    run_number: Annotated[int, typer.Option(help="CI run number whose builds to surface")],
    repository: Annotated[str, typer.Option(help="GitHub repository (owner/repo)")],
    sha: Annotated[str, typer.Option(help="Commit SHA being released")],
    actor: Annotated[str, typer.Option(help="GitHub actor for registry auth")],
    run_id: Annotated[str, typer.Option(help="CI run id for the actions URL")],
    step_summary: Annotated[str | None, typer.Option(help="Path to $GITHUB_STEP_SUMMARY file")] = None,
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    if not any(app.builds for app in publish_config.apps.values()):
        return

    tag = f"{PR_DRAFT_TAG_PREFIX}{pr_number}"
    resolved_run_number = str(run_number)
    staged = publish_draft_assets(
        publish_config,
        resolved_run_number,
        actor,
        settings.github_token,
        tag,
        repository,
        sha,
    )
    manifest = pull_digest_manifest(publish_config.builds_registry, resolved_run_number, actor, settings.github_token)
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"

    pr_url = f"https://github.com/{repository}/pull/{pr_number}"

    assets = [AssetLink(name, f"https://github.com/{repository}/releases/download/{tag}/{name}") for name, _ in staged]

    section = render_draft_section(
        DraftSection(
            heading_fragments=[
                f"[Run #{resolved_run_number}]({run_url})",
                f"[PR #{pr_number}]({pr_url})",
            ],
            assets=assets or None,
            images=manifest,
        )
    )

    append_draft_section(tag, repository, f"run-{resolved_run_number}", section)

    summary_lines = [f"### Draft release `{tag}`", ""]
    summary_lines.extend(render_asset_links(assets))
    summary = "\n".join(summary_lines)
    print(summary)
    write_step_summary(step_summary, summary)
