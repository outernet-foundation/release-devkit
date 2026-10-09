from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from ci_devkit.ci_step import ci_step

from release_devkit.config import DEFAULT_CONFIG_PATH, PublishConfig, load_config
from release_devkit.plan import compute_release_plan
from release_devkit.verbs.lint_workflows import RELEASE_WORKFLOW

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    publish_config = load_config(config)

    with ci_step("Validate delivery surface"):
        validate_delivery_surface(publish_config)

    with ci_step("Validate publish plan"):
        compute_release_plan(publish_config)


def validate_delivery_surface(publish_config: PublishConfig) -> None:
    if not (publish_config.packages or publish_config.apps):
        return
    if not RELEASE_WORKFLOW.is_file():
        raise SystemExit(
            f"release-devkit.yaml declares packages/apps but {RELEASE_WORKFLOW} is missing (the delivery surface)"
        )
