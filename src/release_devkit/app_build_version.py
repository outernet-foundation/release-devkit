from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic_settings import BaseSettings

from .config import load_config
from .ledger import GitLedger

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

DEFAULT_CONFIG_PATH = Path("release-devkit.json")


class Settings(BaseSettings):
    github_run_number: str = ""
    github_ref_name: str = ""


@app.command()
def main(
    application: Annotated[str, typer.Option("--app", help="App name (the release-devkit.json apps[] name)")],
    config: Annotated[Path, typer.Option(help="Publish configuration JSON")] = DEFAULT_CONFIG_PATH,
    run_number: Annotated[
        int, typer.Option(help="Build number baked into the version (defaults to GITHUB_RUN_NUMBER)")
    ] = 0,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    entry = next((candidate for candidate in publish_config.apps if candidate.name == application), None)
    if entry is None:
        names = ", ".join(candidate.name for candidate in publish_config.apps)
        raise SystemExit(f"Unknown app '{application}'. Valid: {names or '(none)'}")

    base_version = GitLedger().latest_version(f"{entry.tag_prefix}-v") or "0.0.0"
    resolved_run_number = str(run_number) if run_number else (settings.github_run_number or "0")
    release = settings.github_ref_name == "main"
    suffix = f"+{resolved_run_number}" if release else f"-dev+{resolved_run_number}"
    print(f"{base_version}{suffix}")
