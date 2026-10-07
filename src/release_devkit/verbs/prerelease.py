from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.drafts import ReleaseChannel, create_or_update_release

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    create_or_update_release(config, ReleaseChannel.DEV)
