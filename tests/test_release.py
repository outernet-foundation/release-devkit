from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from release_devkit.verbs import release
from release_devkit.config import AppConfig, PublishConfig
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
    def create_and_push_tag(self, tag: str) -> None:
        pass


def null_ci_step(label: str) -> object:
    return nullcontext()


def noop(*args: object, **kwargs: object) -> None:
    pass


def test_release_resets_dev_draft_after_create(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_WORKSPACE": "/workspace",
        "GITHUB_STEP_SUMMARY": "",
    }.items():
        monkeypatch.setenv(key, value)

    config = PublishConfig(
        ci_workflow="integrate.yml",
        apps={"myapp": AppConfig(path=Path("apps/myapp"), major_minor="1.0")},
    )
    release_plan = ReleasePlan(
        plans={},
        publishing=set(),
        resolved_versions={},
        app_last_versions={"myapp": None},
        app_versions={"myapp": "1.0.0"},
    )
    monkeypatch.setattr(release, "load_config", FixedReturn(config))
    monkeypatch.setattr(release, "compute_and_print_plan", FixedReturn(release_plan))
    monkeypatch.setattr(release, "GitTags", FixedReturn(FakeTags()))
    monkeypatch.setattr(release, "ci_step", null_ci_step)
    monkeypatch.setattr(release, "setup_publishing_environment", noop)
    monkeypatch.setattr(release, "cut_github_release", noop)
    delete_recorder = CallRecorder()
    monkeypatch.setattr(release, "delete_draft_release", delete_recorder)

    release.main()

    assert delete_recorder.calls == [(DEV_DRAFT_TAG, "owner/repo")]
