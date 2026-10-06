from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..config import DEFAULT_CONFIG_PATH, Settings, load_config, write_step_summary
from ..builds import (
    builds_registry_of,
    pull_digest_manifest,
    render_images_table,
)
from ..drafts import (
    append_draft_section,
    publish_draft_assets,
)

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"


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
    staged = publish_draft_assets(
        publish_config,
        resolved_run_number,
        settings.github_actor,
        settings.github_token,
        tag,
        settings.github_repository,
        settings.github_sha,
    )
    manifest = pull_digest_manifest(
        builds_registry_of(publish_config), resolved_run_number, settings.github_actor, settings.github_token
    )
    run_url = f"https://github.com/{settings.github_repository}/actions/runs/{settings.github_run_id}"

    pr_url = f"https://github.com/{settings.github_repository}/pull/{pr_number}"
    section_lines = [f"### [Run #{resolved_run_number}]({run_url}) \u2014 [PR #{pr_number}]({pr_url})"]
    if manifest:
        section_lines.append("")
        section_lines.append("#### Built images")
        section_lines.extend(render_images_table(manifest))
    if staged:
        section_lines.append("")
        for name, _ in staged:
            url = f"https://github.com/{settings.github_repository}/releases/download/{tag}/{name}"
            section_lines.append(f"- [{name}]({url})")
    section = "\n".join(section_lines)

    append_draft_section(tag, settings.github_repository, f"run-{resolved_run_number}", section)

    summary_lines = [f"### Draft release `{tag}`", ""]
    for name, _ in staged:
        url = f"https://github.com/{settings.github_repository}/releases/download/{tag}/{name}"
        summary_lines.append(f"- [{name}]({url})")
    summary = "\n".join(summary_lines)
    print(summary)
    write_step_summary(settings.github_step_summary, summary)
