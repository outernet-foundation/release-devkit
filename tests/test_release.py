from __future__ import annotations

from pathlib import Path

import pytest

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


class FakeTags:
    def latest_version(self, prefix: str) -> str | None:
        return None

    def create_and_push_tag(self, tag: str) -> None:
        pass


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
    monkeypatch.setattr(release, "print_plan", noop)
    monkeypatch.setattr(release, "GitTags", FixedReturn(FakeTags()))
    monkeypatch.setattr(release, "bash_output", FixedReturn("0"))
    monkeypatch.setattr(release, "pull_build_assets", FixedReturn([]))
    monkeypatch.setattr(release, "bash", noop)
    delete_recorder = CallRecorder()
    monkeypatch.setattr(release, "delete_draft_release", delete_recorder)

    release.main()

    assert delete_recorder.calls == [(DEV_DRAFT_TAG, "owner/repo")]
