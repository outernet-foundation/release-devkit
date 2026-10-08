from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH, load_config
from release_devkit.plan import next_version
from release_devkit.tags import get_latest_version, latest_version_in_line

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    application: Annotated[str, typer.Option("--app", help="App name (the release-devkit.yaml apps key)")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    publish_config = load_config(config)
    if application not in publish_config.apps:
        names = ", ".join(publish_config.apps)
        raise SystemExit(f"Unknown app '{application}'. Valid: {names or '(none)'}")

    app_config = publish_config.apps[application]
    prefix = f"{application}-v"
    last_version = get_latest_version(prefix)
    last_in_line = latest_version_in_line(prefix, app_config.major_minor)
    base_version = next_version(app_config.major_minor, last_in_line, last_version, application)
    count = int(bash_output("git rev-list --count HEAD").strip())
    lines = [f"version={base_version}+{count}", f"version-code={count}"]
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as file:
            file.writelines(line + "\n" for line in lines)
    else:
        for line in lines:
            print(line)
