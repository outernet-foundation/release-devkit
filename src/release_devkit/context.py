from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from bashrun.bash import bash_output
from ci_devkit.builds import build_exists, pull_build

from release_devkit.builds import DIGEST_FILE_NAME, DIGEST_PLATFORM, DIGEST_PROJECT, DigestEntry
from release_devkit.config import DEFAULT_CONFIG_PATH, PublishConfig, Settings, load_config


@dataclass
class VerbContext:
    settings: Settings
    publish_config: PublishConfig
    head: str
    certified: str
    manifest: dict[str, DigestEntry] | None

    @property
    def short(self) -> str:
        return self.certified[:12]

    @property
    def commit_url(self) -> str:
        return f"https://github.com/{self.settings.github_repository}/commit/{self.certified}"


def merge_push_context(config: Path = DEFAULT_CONFIG_PATH) -> VerbContext:
    head = bash_output("git rev-parse HEAD").strip()
    parents = bash_output(f"git log -1 --format=%P {head}").strip().split()
    return build_context(head, parents[1] if len(parents) >= 2 else head, config)


def pr_head_context(config: Path = DEFAULT_CONFIG_PATH) -> VerbContext:
    head = bash_output("git rev-parse HEAD").strip()
    return build_context(head, head, config)


def build_context(head: str, certified: str, config: Path) -> VerbContext:
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
    publish_config = load_config(config)
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
        publish_config=publish_config,
        head=head,
        certified=certified,
        manifest=manifest,
    )
