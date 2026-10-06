from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, Settings, load_config
from release_devkit.plan import compute_and_print_plan
from release_devkit.tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)

    with ci_step("Validate publish plan"):
        compute_and_print_plan(publish_config, GitTags(), settings.github_step_summary)
