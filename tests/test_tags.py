from pathlib import Path

import pytest

from release_devkit.plan import has_changes_since, list_tag_versions
from release_devkit.verbs.release import create_and_push_tag


class CommandRecorder:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[str] = []

    def __call__(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        self.commands.append(command)
        return self.output


def test_list_tag_versions_parses_and_strips_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = CommandRecorder(output="pkg-v1.0.0\npkg-v0.9.0\n")
    monkeypatch.setattr("release_devkit.plan.bash_output", recorder)

    assert list_tag_versions("pkg-v") == ["1.0.0", "0.9.0"]
    assert recorder.commands == ['git tag --list "pkg-v*" --sort=-v:refname']


def test_list_tag_versions_empty_when_no_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("release_devkit.plan.bash_output", CommandRecorder(output=""))

    assert list_tag_versions("pkg-v") == []


def test_has_changes_since_without_tag_is_true() -> None:
    assert has_changes_since(None, Path("pkg")) is True


def always_clean_diff(_command: str) -> bool:
    return False


def test_has_changes_since_negates_quiet_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("release_devkit.plan.bash_check", always_clean_diff)

    assert has_changes_since("pkg-v1.0.0", Path("pkg")) is True


def test_create_and_push_tag_tags_and_pushes(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.verbs.release.bash", recorder)

    create_and_push_tag("pkg-v1.0.1")

    assert recorder.commands == ["git tag pkg-v1.0.1", "git push origin pkg-v1.0.1"]
