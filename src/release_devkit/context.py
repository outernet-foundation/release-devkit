from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from ci_devkit.builds import build_exists, pull_build

from release_devkit.builds import DIGEST_FILE_NAME, DIGEST_PLATFORM, DIGEST_PROJECT, DigestEntry
from release_devkit.config import PublishConfig, Settings


@dataclass
class VerbContext:
    settings: Settings
    head: str
    certified: str
    manifest: dict[str, DigestEntry] | None

    @property
    def short(self) -> str:
        return self.certified[:12]

    @property
    def commit_url(self) -> str:
        return f"https://github.com/{self.settings.github_repository}/commit/{self.certified}"


def build_context(head: str, certified: str, publish_config: PublishConfig) -> VerbContext:
    settings = Settings.model_validate({})
    missing = [
        env_var
        for env_var, value in (
            ("GITHUB_REPOSITORY", settings.github_repository),
            ("GITHUB_ACTOR", settings.github_actor),
            ("GITHUB_WORKSPACE", settings.github_workspace),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"{', '.join(missing)} not set — these verbs read the GitHub runner environment")
    manifest = None
    if publish_config.builds_registry is not None and build_exists(
        publish_config.builds_registry,
        DIGEST_PROJECT,
        DIGEST_PLATFORM,
        f"sha-{certified}",
        registry_username=settings.github_actor,
        registry_token=settings.github_token,
    ):
        digest_staging = Path(mkdtemp(prefix="digest-manifest-"))
        pull_build(
            publish_config.builds_registry,
            DIGEST_PROJECT,
            DIGEST_PLATFORM,
            f"sha-{certified}",
            digest_staging,
            registry_username=settings.github_actor,
            registry_token=settings.github_token,
        )
        data = json.loads((digest_staging / DIGEST_FILE_NAME).read_text(encoding="utf-8"))
        manifest = {target: DigestEntry.model_validate(entry) for target, entry in data.items()}
    return VerbContext(
        settings=settings,
        head=head,
        certified=certified,
        manifest=manifest,
    )
