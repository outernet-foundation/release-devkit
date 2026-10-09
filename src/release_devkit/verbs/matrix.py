from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import TypeAdapter, ValidationError

from release_devkit.config import DEFAULT_CONFIG_PATH, AppConfig, PublishConfig, load_config
from release_devkit.plan import get_latest_version, latest_version_in_line, next_version

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

OUTPUT_KEY = "matrix"
LEGS = TypeAdapter(list[dict[str, object]])


@app.command()
def main(
    key: Annotated[
        str, typer.Option(help="Output key the envelope lands under (job output name at the call site)")
    ] = OUTPUT_KEY,
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    try:
        document = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise SystemExit(f"stdin is not valid JSON: {error}") from error
    try:
        legs = LEGS.validate_python(document)
    except ValidationError as error:
        raise SystemExit(f"stdin must be a JSON array of leg objects: {error}") from error
    if not legs:
        raise SystemExit("empty leg list — refusing to emit an empty matrix envelope")
    publish_config = load_config(config)
    owners = owning_apps_by_project(publish_config)
    base_versions: dict[str, str] = {}
    for leg in legs:
        project = leg.get("project")
        if project is None:
            continue
        if not isinstance(project, str):
            raise SystemExit(f"leg 'project' must be a string, got '{project}'")
        application = owners.get(project)
        if application is None:
            continue
        if application not in base_versions:
            base_versions[application] = app_base_version(publish_config.apps[application], application)
        leg["version"] = base_versions[application]
    envelope = json.dumps({"include": legs}, separators=(",", ":"))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as file:
            file.write(f"{key}={envelope}\n")
    else:
        print(f"{key}={envelope}")


def owning_apps_by_project(publish_config: PublishConfig) -> dict[str, str]:
    owners: dict[str, str] = {}
    for application, app_config in publish_config.apps.items():
        for build in app_config.builds:
            existing = owners.get(build.project)
            if existing is not None and existing != application:
                raise SystemExit(f"project '{build.project}' is built by apps '{existing}' and '{application}'")
            owners[build.project] = application
    return owners


def app_base_version(app_config: AppConfig, application: str) -> str:
    prefix = f"{application}-v"
    last_version = get_latest_version(prefix)
    last_in_line = latest_version_in_line(prefix, app_config.major_minor)
    return next_version(app_config.major_minor, last_in_line, last_version, application)
