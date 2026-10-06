from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from tempfile import mkdtemp

import pytest

from release_devkit import drafts
from release_devkit.verbs import update_pr_draft as update_pr_draft_module
from release_devkit.config import AppConfig, BuildArtifactConfig, BuildsConfig, PublishConfig
from release_devkit.builds import DigestEntry, pull_build_assets
from release_devkit.drafts import (
    append_draft_section,
    delete_draft_release,
)
from release_devkit.verbs.update_pr_draft import update_pr_draft


def null_ci_step(label: str) -> object:
    return nullcontext()


class BashLog:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def __call__(self, command: str) -> None:
        self.commands.append(command)


class FixedReturn:
    def __init__(self, value: object) -> None:
        self.value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.value


def make_build_config() -> PublishConfig:
    return PublishConfig(
        ci_workflow="integrate.yml",
        apps={
            "myapp": AppConfig(
                path=Path("apps/myapp"),
                major_minor="1.0",
                builds=BuildsConfig(
                    registry="ghcr.io/owner/repo/builds",
                    artifacts=[
                        BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
                    ],
                ),
            )
        },
    )


def make_empty_config() -> PublishConfig:
    return PublishConfig(
        ci_workflow="integrate.yml",
        apps={"myapp": AppConfig(path=Path("apps/myapp"), major_minor="1.0")},
    )


def make_source_file(name: str = "app.apk") -> Path:
    directory = Path(mkdtemp(prefix="test-source-"))
    source = directory / name
    source.write_text("build content", encoding="utf-8")
    return source


def patch_verb_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_ACTOR": "bot",
        "GITHUB_TOKEN": "token",
        "GITHUB_RUN_ID": "99",
        "GITHUB_STEP_SUMMARY": "",
    }.items():
        monkeypatch.setenv(key, value)


def patch_bash(monkeypatch: pytest.MonkeyPatch, check_returns: object = False) -> BashLog:
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(check_returns))
    bash_log = BashLog()
    monkeypatch.setattr(drafts, "bash", bash_log)
    return bash_log


def test_pull_build_assets_returns_empty_when_no_builds() -> None:
    result = pull_build_assets(make_empty_config(), "42", "", "")
    assert result == []


def test_delete_draft_release_deletes_with_cleanup_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=True)

    delete_draft_release("pr-7", "owner/repo")

    assert any(
        "gh release delete pr-7" in command and "--cleanup-tag" in command and "--yes" in command
        for command in bash_log.commands
    )


def test_delete_draft_release_noop_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)

    delete_draft_release("pr-7", "owner/repo")

    assert not bash_log.commands


def test_update_pr_draft_derives_pr_tag_and_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_verb_environment(monkeypatch)
    source = make_source_file("MyApp.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
    monkeypatch.setattr(update_pr_draft_module, "load_config", FixedReturn(make_build_config()))
    monkeypatch.setattr(drafts, "pull_build_assets", FixedReturn([(artifact, source)]))
    monkeypatch.setattr(update_pr_draft_module, "pull_digest_manifest", FixedReturn(None))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(""))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft(pr_number=7, run_number=42)

    assert any("pr-7" in command for command in bash_log.commands)
    assert any("gh release upload pr-7" in command and "--clobber" in command for command in bash_log.commands)
    assert any("MyApp-AndroidMobile-run-42.apk" in command for command in bash_log.commands)
    assert any("gh release edit pr-7" in command and "--notes-file" in command for command in bash_log.commands)


def test_update_pr_draft_writes_image_section_when_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_verb_environment(monkeypatch)
    source = make_source_file("MyApp.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest="sha256:abc", tags=["tree-1"])}
    monkeypatch.setattr(update_pr_draft_module, "load_config", FixedReturn(make_build_config()))
    monkeypatch.setattr(drafts, "pull_build_assets", FixedReturn([(artifact, source)]))
    monkeypatch.setattr(update_pr_draft_module, "pull_digest_manifest", FixedReturn(manifest))
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(""))

    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    update_pr_draft(pr_number=7, run_number=42)

    assert written
    assert "zed-capture" in written[0]
    assert "sha256:abc" in written[0]
    assert "https://github.com/owner/repo/actions/runs/99" in written[0]


def test_update_pr_draft_noop_on_empty_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_verb_environment(monkeypatch)
    monkeypatch.setattr(update_pr_draft_module, "load_config", FixedReturn(make_empty_config()))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft(pr_number=7, run_number=42)

    assert not bash_log.commands


def test_append_draft_section_writes_notes_file(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(""))

    append_draft_section("dev-builds", "owner/repo", "run-42", "### Heading")

    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)
