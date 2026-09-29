from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from .artifacts import ARTIFACT_DIR, is_release_artifact
from .config import load_config

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_sha: str
    github_repository: str
    github_output: str | None = None


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")],
    ci_run_id: Annotated[str | None, typer.Option(help="Override CI run lookup with a known run ID")] = None,
) -> None:
    run_fetch_ci_artifacts(config, ci_run_id)


def run_fetch_ci_artifacts(config: Path, ci_run_id: str | None = None) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    repo = settings.github_repository

    if ci_run_id:
        run_id = ci_run_id
        print(f"  Using override CI run: {run_id}")
    else:
        sha = bash_output(f'gh api "/repos/{repo}/git/commits/{settings.github_sha}" --jq ".parents[1].sha"').strip()

        with ci_step("Find successful CI run"):
            run_id = bash_output(
                f'gh api "/repos/{repo}/actions/workflows/{publish_config.ci_workflow}/runs'
                f'?head_sha={sha}&status=success" --jq ".workflow_runs[0].id // empty"'
            ).strip()

            if not run_id:
                print(f"::error::No successful CI run found for SHA {sha}. Cannot release untested code.")
                raise typer.Exit(code=1)

            print(f"  CI run: {run_id}")

    if settings.github_output:
        with Path(settings.github_output).open("a", encoding="utf-8") as file:
            file.write(f"run_id={run_id}\n")

    artifact_dir = ARTIFACT_DIR
    with ci_step("Download artifacts"):
        bash(f"gh run download {run_id} --repo {repo} --dir {artifact_dir}")

        if not artifact_dir.is_dir():
            print("  No artifacts downloaded")
            return

        downloaded = 0
        for entry in sorted(artifact_dir.iterdir()):
            if not entry.is_dir():
                continue
            if not is_release_artifact(entry.name):
                print(f"  Removed: {entry.name}")
                rmtree(entry)
                continue
            downloaded += 1
            print(f"  Kept: {entry.name}")

        print(f"  {downloaded} artifact(s) ready in {artifact_dir}")
