from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..config import DEFAULT_CONFIG_PATH, Settings, load_config
from ..tags import GitTags
from ..plan import next_version

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    application: Annotated[str, typer.Option("--app", help="App name (the release-devkit.yaml apps key)")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
    run_number: Annotated[
        int, typer.Option(help="Build number baked into the version (defaults to the ambient CI run number)")
    ] = 0,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    if application not in publish_config.apps:
        names = ", ".join(publish_config.apps)
        raise SystemExit(f"Unknown app '{application}'. Valid: {names or '(none)'}")

    app_config = publish_config.apps[application]
    tags = GitTags()
    prefix = f"{application}-v"
    last_version = tags.latest_version(prefix)
    last_in_line = tags.latest_version_in_line(prefix, app_config.major_minor)
    base_version = next_version(app_config.major_minor, last_in_line, last_version, application)
    resolved_run_number = str(run_number) if run_number else (settings.github_run_number or "0")
    print(f"{base_version}+{resolved_run_number}")
