from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from tempfile import mkdtemp

import pytest

from release_devkit import drafts
from release_devkit import plan as plan_module
from release_devkit.verbs import update_pr_draft as update_pr_draft_module
from release_devkit.config import AppConfig, BuildArtifactConfig, PublishConfig, Settings
from release_devkit.builds import DigestEntry, pull_build_assets
from release_devkit.context import VerbContext
from release_devkit.drafts import (
    delete_draft_release,
    write_draft_section,
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


class CallRecorder:
    def __init__(self, return_value: object = None) -> None:
        self._return_value = return_value
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append(args)
        return self._return_value


class FakeTags:
    def __init__(self, versions: dict[str, str | None], changed: set[str]) -> None:
        self._versions = versions
        self._changed = changed

    def latest_version(self, prefix: str) -> str | None:
        return self._versions.get(prefix.removesuffix("-v"))

    def has_changes_since(self, tag: str | None, path: Path) -> bool:
        if tag is None:
            return True
        return tag.rsplit("-v", 1)[0] in self._changed


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
    monkeypatch.setattr(plan_module, "latest_version", tags.latest_version)
    monkeypatch.setattr(plan_module, "has_changes_since", tags.has_changes_since)


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
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"}))
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
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"}))
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


def test_update_pr_draft_lists_images_without_any_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest="sha256:abc", tags=["tree-1"])}
    config = PublishConfig(apps={}, builds_registry="ghcr.io/owner/repo/builds")
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(make_context(config, manifest=manifest)))
    monkeypatch.setattr(drafts, "pull_build_assets", FixedReturn([]))
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


def test_update_pr_draft_no_app_builds_uploads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(make_context(make_empty_config())))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft()

    assert not any("gh release upload" in command for command in bash_log.commands)
    assert not any("gh release edit" in command for command in bash_log.commands)


def test_update_pr_draft_skips_when_nothing_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(make_context(make_build_config())))
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed=set()))
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))
    bash_log = patch_bash(monkeypatch, check_returns=False)
    pull_assets = CallRecorder([])
    monkeypatch.setattr(drafts, "pull_build_assets", pull_assets)

    update_pr_draft()

    assert pull_assets.calls == []
    assert not any("gh release upload" in command for command in bash_log.commands)
    assert not any("gh release edit" in command for command in bash_log.commands)


def test_update_pr_draft_refuses_non_pull_request_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    context = make_context(make_build_config(), github_ref="refs/heads/dev")
    monkeypatch.setattr(update_pr_draft_module, "pr_head_context", FixedReturn(context))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    with pytest.raises(IndexError):
        update_pr_draft()

    assert not bash_log.commands


def test_write_draft_section_writes_notes_file_without_recreating(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=True)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))

    context = make_context(PublishConfig())
    write_draft_section(context, "dev-builds", ["Heading"], stage_changed_only=False, publishing=True)

    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)
    assert not any("gh release create" in command for command in bash_log.commands)


def test_write_draft_section_creates_missing_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(DRAFT_VIEW_JSON))

    context = make_context(PublishConfig())
    write_draft_section(context, "dev-builds", ["Heading"], stage_changed_only=False, publishing=True)

    assert any(
        "gh release create dev-builds" in command and "--draft" in command and f"--target {context.head}" in command
        for command in bash_log.commands
    )
    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)


def test_write_draft_section_replaces_same_anchor_and_preserves_others(monkeypatch: pytest.MonkeyPatch) -> None:
    body = f'<a id="sha-old"></a>\n### Old\n\n<a id="sha-{SHORT_SHA}"></a>\n### New v1'
    view_json = json.dumps({"body": body, "url": DRAFT_URL})
    patch_bash(monkeypatch, check_returns=True)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(view_json))

    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    write_draft_section(
        make_context(PublishConfig()), "dev-builds", ["New v2"], stage_changed_only=False, publishing=True
    )

    assert written
    assert "### Old" in written[0]
    assert "### New v2" in written[0]
    assert "### New v1" not in written[0]


def test_write_draft_section_carries_assets_from_newest_section_and_drops_staged_stems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_link = "- [MyApp-AndroidMobile-111111111111.apk](https://github.com/owner/repo/releases/download/dev-builds/MyApp-AndroidMobile-111111111111.apk)"
    replaced_link = "- [OtherApp-Android-222222222222.apk](https://github.com/owner/repo/releases/download/dev-builds/OtherApp-Android-222222222222.apk)"
    stale_link = "- [OtherApp-Android-333333333333.apk](https://github.com/owner/repo/releases/download/dev-builds/OtherApp-Android-333333333333.apk)"
    body = (
        f'<a id="sha-newest"></a>\n### Newest\n{old_link}\n{replaced_link}\n\n'
        f'<a id="sha-old"></a>\n### Old\n{stale_link}'
    )
    view_json = json.dumps({"body": body, "url": DRAFT_URL})
    patch_bash(monkeypatch, check_returns=True)
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(view_json))
    monkeypatch.setattr(
        drafts,
        "pull_build_assets",
        FixedReturn([
            (
                BuildArtifactConfig(project="OtherApp", platform="Android", name="OtherApp-Android.apk"),
                make_source_file("OtherApp-Android.apk"),
            )
        ]),
    )

    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    write_draft_section(
        make_context(make_build_config()), "dev-builds", ["Run"], stage_changed_only=False, publishing=True
    )

    assert written
    anchor = f"sha-{SHORT_SHA}"
    section = written[0].split(f'<a id="{anchor}"></a>', 1)[1].split('<a id="sha-newest"></a>', 1)[0]
    assert old_link in section
    assert f"OtherApp-Android-{SHORT_SHA}.apk" in section
    assert "OtherApp-Android-222222222222.apk" not in section
    assert "OtherApp-Android-333333333333.apk" not in section


def test_write_draft_section_guard_compares_manifest_digests_against_body(monkeypatch: pytest.MonkeyPatch) -> None:
    known = "sha256:" + "a" * 64
    fresh = "sha256:" + "b" * 64
    bash_log = patch_bash(monkeypatch, check_returns=True)

    known_body = json.dumps({"body": f"| img | tree-1 | `{known}` |", "url": DRAFT_URL})
    monkeypatch.setattr(drafts, "bash_output", FixedReturn(known_body))
    context = make_context(
        PublishConfig(), manifest={"img": DigestEntry(ref="ghcr.io/owner/repo/img", digest=known, tags=["tree-1"])}
    )
    write_draft_section(context, "dev-builds", ["Heading"], stage_changed_only=False)
    assert not any("gh release edit" in command for command in bash_log.commands)

    monkeypatch.setattr(drafts, "bash_output", FixedReturn(json.dumps({"body": "", "url": DRAFT_URL})))
    context = make_context(
        PublishConfig(), manifest={"img": DigestEntry(ref="ghcr.io/owner/repo/img", digest=fresh, tags=["tree-1"])}
    )
    write_draft_section(context, "dev-builds", ["Heading"], stage_changed_only=False)
    assert any("gh release edit" in command for command in bash_log.commands)
