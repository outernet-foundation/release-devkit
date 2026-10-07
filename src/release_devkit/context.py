from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bashrun.bash import bash_output

from release_devkit.builds import DigestEntry, certified_sha, pull_digest_manifest
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
    return build_context(head, certified_sha(head), config)


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
    manifest = pull_digest_manifest(
        publish_config.builds_registry,
        certified,
        settings.github_actor,
        settings.github_token,
    )
    return VerbContext(
        settings=settings,
        publish_config=publish_config,
        head=head,
        certified=certified,
        manifest=manifest,
    )
