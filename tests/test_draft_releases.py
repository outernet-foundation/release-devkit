from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_devkit import plan as plan_module
from release_devkit.config import AppConfig, BuildArtifactConfig, PublishConfig
from release_devkit.plan import ReleasePlan
from release_devkit.verbs import release as release_module
from release_devkit.verbs.release import (
    DIGEST_FILE_NAME,
    DigestEntry,
    ReleaseChannel,
    delete_draft_release,
)

DRAFT_URL = "https://github.com/owner/repo/releases/untagged-abc"
DRAFT_VIEW_JSON = json.dumps({"body": "", "url": DRAFT_URL})
DRAFT_REPOSITORY = "owner/repo"
CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]


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


def digest_layer(manifest: dict[str, DigestEntry]) -> dict[tuple[str, str], dict[str, str]]:
    data = {name: entry.model_dump() for name, entry in manifest.items()}
    return {("images-digests", "all"): {DIGEST_FILE_NAME: json.dumps(data)}}


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
    monkeypatch.setattr(plan_module, "get_latest_version", tags.latest_version)
    monkeypatch.setattr(plan_module, "has_changes_since", tags.has_changes_since)
    monkeypatch.setattr(release_module, "get_latest_version", tags.latest_version)


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


def patch_context(
    monkeypatch: pytest.MonkeyPatch,
    publish_config: PublishConfig,
    github_ref: str = "refs/pull/7/merge",
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", DRAFT_REPOSITORY)
    monkeypatch.setenv("GITHUB_ACTOR", "bot")
    monkeypatch.setenv("GITHUB_WORKSPACE", "/workspace")
    monkeypatch.setenv("GITHUB_REF", github_ref)
    monkeypatch.setattr(release_module, "load_config", FixedReturn(publish_config))
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(ReleasePlan.empty()))


def patch_bash(monkeypatch: pytest.MonkeyPatch, check_returns: object = False) -> BashLog:
    monkeypatch.setattr(release_module, "bash_check", FixedReturn(check_returns))
    bash_log = BashLog()
    monkeypatch.setattr(release_module, "bash", bash_log)
    return bash_log


def patch_pr_bash_output(monkeypatch: pytest.MonkeyPatch, body: str = "") -> None:
    def dispatching_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return CERTIFIED_SHA
        return json.dumps({"body": body})

    monkeypatch.setattr(release_module, "bash_output", dispatching_bash_output)


def patch_pull_artifact(
    monkeypatch: pytest.MonkeyPatch, layers: dict[tuple[str, str], dict[str, str]]
) -> FakePullArtifact:
    pull_artifact = FakePullArtifact(layers)
    monkeypatch.setattr(release_module, "pull_artifact", pull_artifact)
    return pull_artifact


def capturing_bash(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    written: list[str] = []

    def capturing(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(release_module, "bash", capturing)
    return written


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
    patch_context(monkeypatch, make_build_config())
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"}))
    patch_pull_artifact(monkeypatch, {("MyApp", "AndroidMobile"): {"MyApp.apk": "build content"}})
    patch_pr_bash_output(monkeypatch)
    bash_log = patch_bash(monkeypatch, check_returns=False)

    release_module.main(channel=ReleaseChannel.PR)

    assert any("pr-7" in command for command in bash_log.commands)
    assert any("gh release upload pr-7" in command and "--clobber" in command for command in bash_log.commands)
    assert any(f"MyApp-AndroidMobile-{SHORT_SHA}.apk" in command for command in bash_log.commands)
    assert any("gh release edit pr-7" in command and "--notes-file" in command for command in bash_log.commands)


def test_update_pr_draft_writes_image_section_when_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest="sha256:abc", tags=["tree-1"])}
    patch_context(monkeypatch, make_build_config())
    patch_pull_artifact(
        monkeypatch, {("MyApp", "AndroidMobile"): {"MyApp.apk": "build content"}, **digest_layer(manifest)}
    )
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"}))
    patch_pr_bash_output(monkeypatch)
    patch_bash(monkeypatch, check_returns=False)
    written = capturing_bash(monkeypatch)

    release_module.main(channel=ReleaseChannel.PR)

    assert written
    assert "zed-capture" in written[0]
    assert "sha256:abc" in written[0]
    assert "[tree-1](https://github.com/orgs/owner/packages/container/repo%2Fzed-capture)" in written[0]
    assert f"https://github.com/owner/repo/commit/{CERTIFIED_SHA}" in written[0]
    assert f"sha-{SHORT_SHA}" in written[0]


def test_update_pr_draft_omits_images_when_manifest_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch, make_build_config())
    patch_pull_artifact(monkeypatch, {("MyApp", "AndroidMobile"): {"MyApp.apk": "build content"}})
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed=set()))
    patch_pr_bash_output(monkeypatch)
    patch_bash(monkeypatch, check_returns=False)
    written = capturing_bash(monkeypatch)

    release_module.main(channel=ReleaseChannel.PR)

    assert written
    assert "Built images" not in written[0]


def test_update_pr_draft_lists_images_without_any_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest="sha256:abc", tags=["tree-1"])}
    config = PublishConfig(apps={}, builds_registry="ghcr.io/owner/repo/builds")
    patch_context(monkeypatch, config)
    patch_pull_artifact(monkeypatch, digest_layer(manifest))
    patch_pr_bash_output(monkeypatch)
    patch_bash(monkeypatch, check_returns=False)
    written = capturing_bash(monkeypatch)

    release_module.main(channel=ReleaseChannel.PR)

    assert written
    assert "zed-capture" in written[0]
    assert "sha256:abc" in written[0]


def test_update_pr_draft_no_app_builds_uploads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch, make_empty_config())
    patch_pr_bash_output(monkeypatch)
    bash_log = patch_bash(monkeypatch, check_returns=False)

    release_module.main(channel=ReleaseChannel.PR)

    assert not any("gh release upload" in command for command in bash_log.commands)
    assert any("gh release edit pr-7" in command for command in bash_log.commands)


def test_update_pr_draft_refuses_non_pull_request_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch, make_build_config(), github_ref="refs/heads/dev")
    patch_pr_bash_output(monkeypatch)
    bash_log = patch_bash(monkeypatch, check_returns=False)

    with pytest.raises(IndexError):
        release_module.main(channel=ReleaseChannel.PR)

    assert not bash_log.commands


def test_update_pr_draft_writes_notes_file_without_recreating(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch, PublishConfig())
    patch_pr_bash_output(monkeypatch)
    bash_log = patch_bash(monkeypatch, check_returns=True)

    release_module.main(channel=ReleaseChannel.PR)

    assert any("gh release edit pr-7" in command and "--notes-file" in command for command in bash_log.commands)
    assert not any("gh release create" in command for command in bash_log.commands)


def test_update_pr_draft_creates_missing_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch, PublishConfig())
    patch_pr_bash_output(monkeypatch)
    bash_log = patch_bash(monkeypatch, check_returns=False)

    release_module.main(channel=ReleaseChannel.PR)

    assert any(
        "gh release create pr-7" in command and "--draft" in command and f"--target {CERTIFIED_SHA}" in command
        for command in bash_log.commands
    )
    assert any("gh release edit pr-7" in command and "--notes-file" in command for command in bash_log.commands)


def test_update_pr_draft_replaces_same_anchor_and_preserves_others(monkeypatch: pytest.MonkeyPatch) -> None:
    body = f'<a id="sha-old"></a>\n### Old\n\n<a id="sha-{SHORT_SHA}"></a>\n### New v1'
    patch_context(monkeypatch, PublishConfig())
    patch_pr_bash_output(monkeypatch, body)
    patch_bash(monkeypatch, check_returns=True)
    written = capturing_bash(monkeypatch)

    release_module.main(channel=ReleaseChannel.PR)

    assert written
    assert "### Old" in written[0]
    assert f"### [{SHORT_SHA}]" in written[0]
    assert "### New v1" not in written[0]


def test_update_pr_draft_lists_one_row_per_staged_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PublishConfig(
        apps={
            "myapp": AppConfig(
                path=Path("apps/myapp"),
                major_minor="1.0",
                builds=[
                    BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk"),
                    BuildArtifactConfig(project="MyApp", platform="IOS", name="MyApp-IOS.apk"),
                ],
            )
        },
        builds_registry="ghcr.io/owner/repo/builds",
    )
    patch_context(monkeypatch, config)
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed=set()))
    patch_pull_artifact(
        monkeypatch,
        {
            ("MyApp", "AndroidMobile"): {"MyApp-AndroidMobile.apk": "build content"},
            ("MyApp", "IOS"): {"MyApp-IOS.apk": "build content"},
        },
    )
    patch_pr_bash_output(monkeypatch)
    patch_bash(monkeypatch, check_returns=False)
    written = capturing_bash(monkeypatch)

    release_module.main(channel=ReleaseChannel.PR)

    assert written
    assert f"| myapp | 1.0.0 | [MyApp-AndroidMobile-{SHORT_SHA}.apk](" in written[0]
    assert f"| myapp | 1.0.0 | [MyApp-IOS-{SHORT_SHA}.apk](" in written[0]
