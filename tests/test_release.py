from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from release_devkit.config import AppConfig, BuildArtifactConfig, PublishConfig
from release_devkit.plan import ReleasePlan
from release_devkit.verbs import release as release_module
from release_devkit.verbs.release import DEV_DRAFT_TAG, ReleaseChannel

HEAD_SHA = "1111111111111111111111111111111111111111"
CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"


class FixedReturn:
    def __init__(self, value: object) -> None:
        self.value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.value


class CallRecorder:
    def __init__(self, return_value: object = None) -> None:
        self.return_value = return_value
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append(args)
        return self.return_value


def noop(*args: object, **kwargs: object) -> None:
    pass


class FakePullArtifact:
    def __init__(self, layers: dict[tuple[str, str], dict[str, str]]) -> None:
        self.layers = layers
        self.calls: list[tuple[object, ...]] = []

    def __call__(
        self,
        builds_registry: str,
        project: str,
        platform: str,
        tag: str,
        target: Path,
        **kwargs: object,
    ) -> bool:
        self.calls.append((builds_registry, project, platform, tag, target))
        files = self.layers.get((project, platform))
        if files is None:
            return False
        target.mkdir(parents=True, exist_ok=True)
        for file_name, content in files.items():
            (target / file_name).write_text(content, encoding="utf-8")
        return True


def patch_stable_context(monkeypatch: pytest.MonkeyPatch, config: PublishConfig) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_ACTOR", "bot")
    monkeypatch.setenv("GITHUB_WORKSPACE", "/workspace")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(release_module, "load_config", FixedReturn(config))
    monkeypatch.setattr(release_module, "configure_git", noop)
    monkeypatch.setattr(release_module, "bash_check", FixedReturn(False))

    def dispatching_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return HEAD_SHA
        if "%P" in command:
            return f"{HEAD_SHA} {CERTIFIED_SHA}\n"
        if command.startswith("gh release list"):
            return "0"
        return json.dumps({"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"})

    monkeypatch.setattr(release_module, "bash_output", dispatching_bash_output)


def test_release_resets_dev_draft_after_create(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PublishConfig(
        apps={
            "myapp": AppConfig(
                path=Path("apps/myapp"),
                major_minor="1.0",
                builds=[BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")],
            )
        },
        builds_registry="ghcr.io/owner/repo/builds",
    )
    release_plan = ReleasePlan(
        plans={},
        publishing=set(),
        resolved_versions={},
        app_last_versions={"myapp": None},
        app_versions={"myapp": "1.0.0"},
    )
    patch_stable_context(monkeypatch, config)
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(release_plan))
    monkeypatch.setattr(release_module, "install_dotnet", noop)
    monkeypatch.setattr(release_module, "install_node", noop)
    monkeypatch.setattr(release_module, "create_and_push_tag", CallRecorder())
    monkeypatch.setattr(
        release_module, "pull_artifact", FakePullArtifact({("MyApp", "AndroidMobile"): {"MyApp.apk": "build content"}})
    )
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(release_module, "bash", capturing_bash)
    delete_recorder = CallRecorder()
    monkeypatch.setattr(release_module, "delete_draft_release", delete_recorder)

    release_module.main(channel=ReleaseChannel.STABLE)

    assert delete_recorder.calls == [(DEV_DRAFT_TAG, "owner/repo")]
    assert len(written) == 1
    release_tag = f"{datetime.now(UTC).strftime('%Y.%m')}.1"
    assert "## Apps" in written[0]
    assert (
        f"| myapp | 1.0.0 | [MyApp-AndroidMobile.apk]"
        f"(https://github.com/owner/repo/releases/download/{release_tag}/MyApp-AndroidMobile.apk) |"
    ) in written[0]
    assert "## Packages" not in written[0]


def test_release_tags_app_versions_before_publishing_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PublishConfig(
        apps={
            "myapp": AppConfig(
                path=Path("apps/myapp"),
                major_minor="1.0",
                builds=[BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")],
            )
        },
        builds_registry="ghcr.io/owner/repo/builds",
    )
    release_plan = ReleasePlan(
        plans={},
        publishing=set(),
        resolved_versions={},
        app_last_versions={"myapp": "1.0.0"},
        app_versions={"myapp": "1.1.0"},
    )
    patch_stable_context(monkeypatch, config)
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(release_plan))
    monkeypatch.setattr(release_module, "install_dotnet", noop)
    monkeypatch.setattr(release_module, "install_node", noop)
    tag_recorder = CallRecorder()
    monkeypatch.setattr(release_module, "create_and_push_tag", tag_recorder)
    monkeypatch.setattr(
        release_module, "pull_artifact", FakePullArtifact({("MyApp", "AndroidMobile"): {"MyApp.apk": "build content"}})
    )
    edit_commands: list[str] = []

    def recording_bash(command: str) -> None:
        if "gh release edit" in command:
            edit_commands.append(command)

    monkeypatch.setattr(release_module, "bash", recording_bash)
    monkeypatch.setattr(release_module, "delete_draft_release", noop)

    release_module.main(channel=ReleaseChannel.STABLE)

    assert tag_recorder.calls == [("myapp-v1.1.0",)]
    assert edit_commands
    assert any("--draft=false" in command for command in edit_commands)


def test_release_stops_when_nothing_to_ship(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_stable_context(monkeypatch, PublishConfig())
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(ReleasePlan.empty()))
    bash_recorder = CallRecorder()
    monkeypatch.setattr(release_module, "bash", bash_recorder)

    release_module.main(channel=ReleaseChannel.STABLE)

    assert bash_recorder.calls == []
