from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, load_config
from release_devkit.plan import compute_and_print_plan
from release_devkit.tags import GitTags

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    step_summary: Annotated[str | None, typer.Option(help="Path to $GITHUB_STEP_SUMMARY file")] = None,
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    publish_config = load_config(config)

    with ci_step("Validate publish plan"):
        compute_and_print_plan(publish_config, GitTags(), step_summary)
