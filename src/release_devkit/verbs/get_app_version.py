from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH, load_config
from release_devkit.tags import GitTags
from release_devkit.plan import next_version

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    application: Annotated[str, typer.Option("--app", help="App name (the release-devkit.yaml apps key)")],
    run_number: Annotated[int, typer.Option(help="Build number baked into the version")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
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
    print(f"{base_version}+{run_number}")
