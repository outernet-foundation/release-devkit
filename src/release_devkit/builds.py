from __future__ import annotations

import json
from pathlib import Path
from tempfile import mkdtemp

import typer
from bashrun.bash import bash_output
from pydantic import BaseModel
from ci_devkit.builds import build_exists, pull_build
from ci_devkit.ci_step import ci_step

from release_devkit.config import BuildArtifactConfig, PublishConfig

DIGEST_PROJECT = "images-digests"
DIGEST_PLATFORM = "all"
DIGEST_FILE_NAME = "images-digests.json"


class DigestEntry(BaseModel):
    ref: str
    digest: str
    tags: list[str]


class MatchedRun(BaseModel):
    run_number: int | None = None
    html_url: str | None = None


def matched_ci_run_number(repository: str, sha: str, ci_workflow: str) -> tuple[str, str]:
    with ci_step("Find successful CI run"):
        parent = bash_output(f'gh api "/repos/{repository}/git/commits/{sha}" --jq ".parents[1].sha // .sha"').strip()
        result = bash_output(
            f'gh api "/repos/{repository}/actions/workflows/{ci_workflow}/runs'
            f'?head_sha={parent}&status=success" '
            f'--jq "{{run_number: .workflow_runs[0].run_number, html_url: .workflow_runs[0].html_url}}"'
        ).strip()
        parsed = MatchedRun.model_validate(json.loads(result)) if result else None
        run_number = str(parsed.run_number) if parsed and parsed.run_number is not None else ""
        html_url = parsed.html_url if parsed and parsed.html_url else ""
        if not run_number or not html_url:
            print(f"::error::No successful CI run found for SHA {parent}. Cannot release untested code.")
            raise typer.Exit(code=1)

        print(f"  CI run number: {run_number}")
        return run_number, html_url


def pull_build_assets(
    publish_config: PublishConfig, run_number: str, registry_username: str, registry_token: str
) -> list[tuple[BuildArtifactConfig, Path]]:
    apps_with_builds = {name: app.builds for name, app in publish_config.apps.items() if app.builds}
    if not apps_with_builds:
        return []

    registry = publish_config.builds_registry
    if registry is None:
        raise ValueError("builds_registry is required when any app declares builds")

    build_tag = f"run-{run_number}"
    staging = Path(mkdtemp(prefix="release-builds-"))
    assets: list[tuple[BuildArtifactConfig, Path]] = []

    for app_name, artifacts in apps_with_builds.items():
        with ci_step(f"Pull build artifacts ({app_name})"):
            for artifact in artifacts:
                target = staging / f"{artifact.project}-{artifact.platform}"
                pull_build(
                    registry,
                    artifact.project,
                    artifact.platform,
                    build_tag,
                    target,
                    registry_username=registry_username,
                    registry_token=registry_token,
                )
                files = sorted(path for path in target.rglob("*") if path.is_file())
                if artifact.file is not None:
                    source = next((path for path in files if path.name == artifact.file), None)
                    if source is None:
                        raise SystemExit(f"Build artifact layer '{artifact.file}' not found under {target}")
                elif len(files) == 1:
                    source = files[0]
                else:
                    raise SystemExit(
                        f"Build artifact for ({artifact.project}, {artifact.platform}) pulled multiple files "
                        f"({', '.join(path.name for path in files)}); declare which one with 'file'"
                    )
                assets.append((artifact, source))
                print(f"  Asset: {source.name}")

    return assets


def pull_digest_manifest(
    builds_registry: str | None,
    run_number: str,
    registry_username: str,
    registry_token: str,
) -> dict[str, DigestEntry] | None:
    if builds_registry is None:
        return None
    tag = f"run-{run_number}"
    if not build_exists(
        builds_registry,
        DIGEST_PROJECT,
        DIGEST_PLATFORM,
        tag,
        registry_username=registry_username,
        registry_token=registry_token,
    ):
        return None
    staging = Path(mkdtemp(prefix="digest-manifest-"))
    pull_build(
        builds_registry,
        DIGEST_PROJECT,
        DIGEST_PLATFORM,
        tag,
        staging,
        registry_username=registry_username,
        registry_token=registry_token,
    )
    data = json.loads((staging / DIGEST_FILE_NAME).read_text(encoding="utf-8"))
    return {target: DigestEntry.model_validate(entry) for target, entry in data.items()}
