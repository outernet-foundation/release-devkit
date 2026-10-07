from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

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
    repository: Annotated[str, typer.Option(help="GitHub repository (owner/repo)")],
    actor: Annotated[str, typer.Option(help="GitHub actor for registry auth")],
    step_summary: Annotated[str | None, typer.Option(help="Path to $GITHUB_STEP_SUMMARY file")] = None,
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    certified = bash_output("git rev-parse HEAD").strip()
    short = certified[:12]
    commit_url = f"https://github.com/{repository}/commit/{certified}"
    manifest = pull_digest_manifest(publish_config.builds_registry, certified, actor, settings.github_token)

    if not any(app.builds for app in publish_config.apps.values()):
        return

    tag = f"{PR_DRAFT_TAG_PREFIX}{pr_number}"
    staged = publish_draft_assets(
        publish_config,
        certified,
        actor,
        settings.github_token,
        tag,
        repository,
        certified,
    )

    pr_url = f"https://github.com/{repository}/pull/{pr_number}"

    assets = [AssetLink(name, f"https://github.com/{repository}/releases/download/{tag}/{name}") for name, _ in staged]

    section = render_draft_section(
        DraftSection(
            heading_fragments=[
                f"[{short}]({commit_url})",
                f"[PR #{pr_number}]({pr_url})",
            ],
            assets=assets or None,
            images=manifest,
        )
    )

    append_draft_section(tag, repository, f"sha-{short}", section)

    summary_lines = [f"### Draft release `{tag}`", ""]
    summary_lines.extend(render_asset_links(assets))
    summary = "\n".join(summary_lines)
    print(summary)
    write_step_summary(step_summary, summary)
