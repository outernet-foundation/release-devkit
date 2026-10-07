from __future__ import annotations

from pathlib import Path

import pytest

from release_devkit import builds as builds_module
from release_devkit import drafts
from release_devkit.verbs import release
from release_devkit.config import AppConfig, PublishConfig, Settings
from release_devkit.context import VerbContext
from release_devkit.drafts import DEV_DRAFT_TAG
from release_devkit.plan import ReleasePlan


class FixedReturn:
    def __init__(self, value: object) -> None:
        self._value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self._value


class CallRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append(args)


def noop(*args: object, **kwargs: object) -> None:
    pass


CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def make_context(publish_config: PublishConfig) -> VerbContext:
    return VerbContext(
        settings=Settings(
            github_token="token",
            github_repository="owner/repo",
            github_actor="bot",
            github_workspace="/workspace",
        ),
        publish_config=publish_config,
        head="1111111111111111111111111111111111111111",
        certified=CERTIFIED_SHA,
        manifest=None,
    )


def test_release_resets_dev_draft_after_create(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PublishConfig(
        apps={"myapp": AppConfig(path=Path("apps/myapp"), major_minor="1.0")},
    )
    release_plan = ReleasePlan(
        plans={},
        publishing=set(),
        resolved_versions={},
        app_last_versions={"myapp": None},
        app_versions={"myapp": "1.0.0"},
    )
    monkeypatch.setattr(release, "merge_push_context", FixedReturn(make_context(config)))
    monkeypatch.setattr(release, "compute_release_plan", FixedReturn(release_plan))
    monkeypatch.setattr(release, "create_and_push_tag", noop)
    monkeypatch.setattr(release, "latest_version", FixedReturn("1.0.0"))
    monkeypatch.setattr(release, "bash_output", FixedReturn("0"))
    monkeypatch.setattr(builds_module, "pull_build_assets", FixedReturn([]))
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)
    delete_recorder = CallRecorder()
    monkeypatch.setattr(release, "delete_draft_release", delete_recorder)

    release.main()

    assert delete_recorder.calls == [(DEV_DRAFT_TAG, "owner/repo")]
    assert len(written) == 1
    assert "## Apps" in written[0]
    assert "| myapp | 1.0.0 | — |" in written[0]
    assert "## Packages" not in written[0]
