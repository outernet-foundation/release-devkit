from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from tempfile import mkdtemp

import pytest

from release_devkit import drafts
from release_devkit.verbs import update_pr_draft as update_pr_draft_module
from release_devkit.config import AppConfig, BuildArtifactConfig, PublishConfig, Settings
from release_devkit.builds import DigestEntry, pull_build_assets
from release_devkit.context import VerbContext
from release_devkit.drafts import (
    delete_draft_release,
)
from release_devkit.verbs.update_pr_draft import update_pr_draft

DRAFT_URL = "https://github.com/owner/repo/releases/untagged-abc"
DRAFT_VIEW_JSON = json.dumps({"body": "", "url": DRAFT_URL})


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
        apps={
            "myapp": AppConfig(
                path=Path("apps/myapp"),
                major_minor="1.0",
                builds=[BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")],
            )
        },
        builds_registry="ghcr.io/owner/repo/builds",
    )


def make_empty_config() -> PublishConfig:
    return PublishConfig(
        apps={"myapp": AppConfig(path=Path("apps/myapp"), major_minor="1.0")},
    )


def make_source_file(name: str = "app.apk") -> Path:
    directory = Path(mkdtemp(prefix="test-source-"))
    source = directory / name
    source.write_text("build content", encoding="utf-8")
    return source


DRAFT_REPOSITORY = "owner/repo"
CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]


def make_context(
    publish_config: PublishConfig,
    manifest: dict[str, DigestEntry] | None = None,
    github_ref: str = "refs/pull/7/merge",
) -> VerbContext:
    return VerbContext(
        settings=Settings(
            github_token="token",
            github_repository=DRAFT_REPOSITORY,
            github_actor="bot",
            github_ref=github_ref,
        ),
        publish_config=publish_config,
        head=CERTIFIED_SHA,
        certified=CERTIFIED_SHA,
        manifest=manifest,
    )


def patch_bash(monkeypatch: pytest.MonkeyPatch, check_returns: object = False) -> BashLog:
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(check_returns))
    bash_log = BashLog()
    monkeypatch.setattr(drafts, "bash", bash_log)
    return bash_log


def test_pull_build_assets_returns_empty_when_no_builds() -> None:
    result = pull_build_assets(make_empty_config(), CERTIFIED_SHA, "", "")
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
    source = make_source_file("MyApp.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(make_context(make_build_config())))
    monkeypatch.setattr(drafts, "pull_build_assets", FixedReturn([(artifact, source)]))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft()

    assert any("pr-7" in command for command in bash_log.commands)
    assert any("gh release upload pr-7" in command and "--clobber" in command for command in bash_log.commands)
    assert any(f"MyApp-AndroidMobile-{SHORT_SHA}.apk" in command for command in bash_log.commands)
    assert any("gh release edit pr-7" in command and "--notes-file" in command for command in bash_log.commands)


def test_update_pr_draft_writes_image_section_when_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    source = make_source_file("MyApp.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest="sha256:abc", tags=["tree-1"])}
    monkeypatch.setattr(
        update_pr_draft_module, "pr_head_context", FixedReturn(make_context(make_build_config(), manifest=manifest))
    )
    monkeypatch.setattr(drafts, "pull_build_assets", FixedReturn([(artifact, source)]))
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))

    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    update_pr_draft()

    assert written
    assert "zed-capture" in written[0]
    assert "sha256:abc" in written[0]
    assert f"https://github.com/owner/repo/commit/{CERTIFIED_SHA}" in written[0]
    assert f"sha-{SHORT_SHA}" in written[0]


def test_update_pr_draft_noop_on_empty_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(make_context(make_empty_config())))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft()

    assert not bash_log.commands


def test_update_pr_draft_refuses_non_pull_request_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    context = make_context(make_build_config(), github_ref="refs/heads/dev")
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(context))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    with pytest.raises(SystemExit, match="GITHUB_REF"):
        update_pr_draft()

    assert not bash_log.commands


def test_upsert_section_writes_notes_file_without_recreating(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=True)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))

    draft = drafts.DraftRelease("dev-builds", "owner/repo", CERTIFIED_SHA)
    draft.upsert_section("run-42", "### Heading")

    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)
    assert not any("gh release create" in command for command in bash_log.commands)


def test_upsert_section_creates_missing_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))

    draft = drafts.DraftRelease("dev-builds", "owner/repo", CERTIFIED_SHA)
    draft.upsert_section("run-42", "### Heading")

    assert any(
        "gh release create dev-builds" in command and "--draft" in command and f"--target {CERTIFIED_SHA}" in command
        for command in bash_log.commands
    )
    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)


def test_upsert_section_replaces_same_anchor_and_preserves_others(monkeypatch: pytest.MonkeyPatch) -> None:
    body = '<a id="sha-old"></a>\n### Old\n\n<a id="sha-new"></a>\n### New v1'
    view_json = json.dumps({"body": body, "url": DRAFT_URL})
    patch_bash(monkeypatch, check_returns=True)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(view_json))

    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    draft = drafts.DraftRelease("dev-builds", "owner/repo", CERTIFIED_SHA)
    draft.upsert_section("sha-new", "### New v2")

    assert written
    assert "### Old" in written[0]
    assert "### New v2" in written[0]
    assert "### New v1" not in written[0]
