from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from .config import DEFAULT_CONFIG_PATH, load_config
from .outputs import append_line
from .plan import compute_release_plan, render_plan_summary
from .tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_step_summary: str | None = None


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)

    with ci_step("Validate publish plan"):
        release_plan = compute_release_plan(publish_config, publish_config.packages, GitTags())
        summary = render_plan_summary(release_plan)
        print(summary)
        append_line(settings.github_step_summary, summary)
