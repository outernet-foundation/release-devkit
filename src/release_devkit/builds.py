from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

from ci_devkit.builds import pull_build
from ci_devkit.ci_step import ci_step
from pydantic import BaseModel

from release_devkit.config import AppConfig, BuildArtifactConfig

DIGEST_PROJECT = "images-digests"
DIGEST_PLATFORM = "all"
DIGEST_FILE_NAME = "images-digests.json"


class DigestEntry(BaseModel):
    ref: str
    digest: str
    tags: list[str]


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
