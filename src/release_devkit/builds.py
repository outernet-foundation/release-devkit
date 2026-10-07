from __future__ import annotations

import json
from pathlib import Path
from tempfile import mkdtemp

from bashrun.bash import bash_output
from pydantic import BaseModel
from ci_devkit.builds import build_exists, pull_build
from ci_devkit.ci_step import ci_step

from release_devkit.config import AppConfig, BuildArtifactConfig

DIGEST_PROJECT = "images-digests"
DIGEST_PLATFORM = "all"
DIGEST_FILE_NAME = "images-digests.json"


class DigestEntry(BaseModel):
    ref: str
    digest: str
    tags: list[str]


def certified_sha(sha: str) -> str:
    parents = bash_output(f"git log -1 --format=%P {sha}").strip().split()
    return parents[1] if len(parents) >= 2 else sha


def pull_build_assets(
    apps: dict[str, AppConfig],
    builds_registry: str | None,
    sha: str,
    registry_username: str,
    registry_token: str,
) -> list[tuple[BuildArtifactConfig, Path]]:
    apps_with_builds = {name: app.builds for name, app in apps.items() if app.builds}
    if not apps_with_builds:
        return []

    if builds_registry is None:
        raise ValueError("builds_registry is required when any app declares builds")

    build_tag = f"sha-{sha}"
    staging = Path(mkdtemp(prefix="release-builds-"))
    assets: list[tuple[BuildArtifactConfig, Path]] = []

    for app_name, artifacts in apps_with_builds.items():
        with ci_step(f"Pull build artifacts ({app_name})"):
            for artifact in artifacts:
                target = staging / f"{artifact.project}-{artifact.platform}"
                pull_build(
                    builds_registry,
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
    sha: str,
    registry_username: str,
    registry_token: str,
) -> dict[str, DigestEntry] | None:
    if builds_registry is None:
        return None
    tag = f"sha-{sha}"
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
