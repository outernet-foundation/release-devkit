from __future__ import annotations

import json
from pathlib import Path
from tempfile import mkdtemp

import pytest

from release_devkit import builds as builds_module
from release_devkit import drafts
from release_devkit import plan as plan_module
from release_devkit import publishing as publishing_module
from release_devkit.config import AppConfig, BuildArtifactConfig, PackageConfig, PublishConfig, Settings
from release_devkit.builds import DigestEntry
from release_devkit.context import VerbContext
from release_devkit.plan import PackagePlan, ReleasePlan
from release_devkit.verbs import prerelease


class FakeTags:
    def __init__(self, versions: dict[str, str | None], changed: set[str]) -> None:
        self._versions = versions
        self._changed = changed

    def latest_version(self, prefix: str) -> str | None:
        name = prefix.removesuffix("-v")
        return self._versions.get(name)

    def latest_version_in_line(self, prefix: str, major_minor: str) -> str | None:
        return self.latest_version(prefix)

    def has_changes_since(self, tag: str | None, path: Path) -> bool:
        if tag is None:
            return True
        name = tag.rsplit("-v", 1)[0]
        return name in self._changed


class FixedReturn:
    def __init__(self, value: object) -> None:
        self._value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self._value


class CallRecorder:
    def __init__(self, return_value: object = None) -> None:
        self._return_value = return_value
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append(args)
        return self._return_value


class FakePublishRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def dev_version(self, base_version: object, short_sha: object) -> object:
        return f"{base_version}-dev.{short_sha}"

    def publish(
        self,
        path: object,
        version: object,
        dependency_versions: object,
        dev: bool,
    ) -> None:
        self.calls.append({
            "path": path,
            "version": version,
            "dependency_versions": dependency_versions,
            "dev": dev,
        })


def make_builds() -> list[BuildArtifactConfig]:
    return [BuildArtifactConfig(project="MyApp", platform="AndroidMobile")]


def make_app(name: str = "myapp", builds: list[BuildArtifactConfig] | None = None) -> AppConfig:
    return AppConfig(path=Path(f"apps/{name}"), major_minor="1.0", builds=builds or make_builds())


def make_config(
    packages: dict[str, PackageConfig] | None = None,
    apps: dict[str, AppConfig] | None = None,
) -> PublishConfig:
    return PublishConfig(
        packages=packages or {},
        apps=apps or {},
        builds_registry="ghcr.io/owner/repo/builds" if apps else None,
    )


def make_plan(publishing: set[str], unchanged: set[str] | None = None) -> ReleasePlan:
    names = publishing | (unchanged or set())
    plans = {
        name: PackagePlan(name=name, publish=name in publishing, version="1.0.0", last_version=None) for name in names
    }
    return ReleasePlan(
        plans=plans,
        publishing=publishing,
        publishing_registries=set(),
        resolved_versions={name: {} for name in publishing},
        app_last_versions={},
        app_versions={},
    )


CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]
MERGE_SHA = "654321abcdef0987654321abcdef0987654321"


def noop(*args: object, **kwargs: object) -> None:
    pass


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
    monkeypatch.setattr(plan_module, "latest_version", tags.latest_version)
    monkeypatch.setattr(plan_module, "latest_version_in_line", tags.latest_version_in_line)
    monkeypatch.setattr(plan_module, "has_changes_since", tags.has_changes_since)
    monkeypatch.setattr(drafts, "latest_version", tags.latest_version)


def make_context(
    config: PublishConfig,
    manifest: dict[str, DigestEntry] | None = None,
) -> VerbContext:
    return VerbContext(
        settings=Settings(
            github_token="token",
            github_repository="owner/repo",
            github_actor="bot",
            github_workspace="/workspace",
        ),
        publish_config=config,
        head=MERGE_SHA,
        certified=CERTIFIED_SHA,
        manifest=manifest,
    )


def make_source_file(name: str) -> Path:
    directory = Path(mkdtemp(prefix="test-source-"))
    source = directory / name
    source.write_text("build content", encoding="utf-8")
    return source


def patch_common(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    manifest: dict[str, DigestEntry] | None = None,
) -> CallRecorder:
    monkeypatch.setattr(publishing_module, "merge_push_context", FixedReturn(make_context(config, manifest)))
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash", CallRecorder())
    monkeypatch.setattr(
        drafts,
        "bash_output",
        FixedReturn('{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}'),
    )
    monkeypatch.setattr(publishing_module, "merge_push_context", FixedReturn(make_context(config, manifest)))
    pull_assets = CallRecorder([])
    monkeypatch.setattr(builds_module, "pull_build_assets", pull_assets)
    monkeypatch.setattr(prerelease, "bash_output", FixedReturn("Merge PR #7: Add the thing\n"))
    return pull_assets


def patch_publish_internals(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePublishRegistry, CallRecorder]:
    npm_registry = FakePublishRegistry()
    create_and_push_tag = CallRecorder()
    monkeypatch.setattr(publishing_module, "configure_git", noop)
    monkeypatch.setattr(publishing_module, "install_dotnet", noop)
    monkeypatch.setattr(publishing_module, "install_node", noop)
    monkeypatch.setattr(publishing_module, "build_registries", FixedReturn({"npm": npm_registry}))
    monkeypatch.setattr(publishing_module, "create_and_push_tag", create_and_push_tag)
    return npm_registry, create_and_push_tag


def run_prerelease(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[FakePublishRegistry, CallRecorder, CallRecorder, list[str]]:
    monkeypatch.setattr(publishing_module, "compute_release_plan", FixedReturn(release_plan))
    patch_plan_tags(monkeypatch, tags)
    pull_assets = patch_common(monkeypatch, config)
    npm_registry, create_and_push_tag = patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    prerelease.main()

    return npm_registry, create_and_push_tag, pull_assets, written


def test_noop_merge_publishes_nothing_but_writes_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    npm_registry, _, pull_assets, written = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert npm_registry.calls == []
    assert pull_assets.calls != []
    assert written != []


def test_only_packages_changed_publishes_and_appends_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={"npm": "pkg-id"})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())
    release_plan = make_plan({"pkg"})

    npm_registry, create_and_push_tag, pull_assets, written = run_prerelease(monkeypatch, config, release_plan, tags)

    assert len(npm_registry.calls) == 1
    assert npm_registry.calls[0]["version"] == f"1.0.0-dev.{SHORT_SHA}"
    assert npm_registry.calls[0]["dev"] is True
    assert create_and_push_tag.calls == []
    assert pull_assets.calls != []
    assert written != []
    assert f'<a id="sha-{SHORT_SHA}"></a>' in written[0]


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    monkeypatch.setattr(publishing_module, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")
    pull_assets = CallRecorder([("myapp", artifact, make_source_file("MyApp-AndroidMobile.apk"))])
    monkeypatch.setattr(builds_module, "pull_build_assets", pull_assets)
    npm_registry, _ = patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    prerelease.main()

    assert npm_registry.calls == []
    assert pull_assets.calls != []
    assert pull_assets.calls[0][2] == CERTIFIED_SHA
    assert len(written) == 1
    assert "#### Apps" in written[0]
    assert "| App | Version | Asset |" in written[0]
    fresh_link = f"https://github.com/owner/repo/releases/download/dev-builds/MyApp-AndroidMobile-{SHORT_SHA}.apk"
    assert f"| myapp | 1.0.0 | [MyApp-AndroidMobile-{SHORT_SHA}.apk]({fresh_link}) |" in written[0]


def test_stages_all_apps_regardless_of_source_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        apps={
            "changed-app": make_app("changed-app"),
            "unchanged-app": make_app("unchanged-app"),
        }
    )
    tags = FakeTags(
        versions={"changed-app": "1.0.0", "unchanged-app": "2.0.0"},
        changed={"changed-app"},
    )

    _, _, pull_assets, _ = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert len(pull_assets.calls) == 1
    assert pull_assets.calls[0][0] == config.apps


def test_any_new_digest_appends_snapshot_section_with_all_images(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_existing = "sha256:" + "a" * 64
    digest_new = "sha256:" + "b" * 64
    manifest = {
        "zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_new, tags=["tree-1"]),
        "other-capture": DigestEntry(ref="ghcr.io/owner/repo/other-capture", digest=digest_existing, tags=["tree-2"]),
    }

    monkeypatch.setattr(publishing_module, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config, manifest=manifest)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    draft_body = (
        f"#### Built images\n| Image | Tag | Digest |\n|---|---|---|\n| other-capture | tree-2 | `{digest_existing}` |"
    )
    monkeypatch.setattr(
        drafts,
        "bash_output",
        FixedReturn(json.dumps({"body": draft_body, "url": "https://github.com/owner/repo/releases/untagged-abc"})),
    )
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    prerelease.main()

    assert len(written) == 1
    assert digest_new in written[0]
    assert digest_existing in written[0]
    assert f"[{SHORT_SHA}](https://github.com/owner/repo/commit/{CERTIFIED_SHA})" in written[0]


def test_snapshot_section_lists_all_packages_with_dev_and_stable_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(
        packages={
            "fresh": PackageConfig(path=Path("packages/fresh"), major_minor="1.0", registries={"npm": "fresh-id"}),
            "settled": PackageConfig(
                path=Path("packages/settled"), major_minor="1.0", registries={"npm": "settled-id"}
            ),
        },
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0", "settled": "2.1.0"}, changed=set())

    monkeypatch.setattr(publishing_module, "compute_release_plan", FixedReturn(make_plan({"fresh"}, {"settled"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    prerelease.main()

    assert len(written) == 1
    assert f"| fresh | 1.0.0-dev.{SHORT_SHA} |" in written[0]
    assert "| settled | 2.1.0 |" in written[0]


def test_existing_dev_draft_viewed_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    monkeypatch.setattr(publishing_module, "compute_release_plan", FixedReturn(make_plan({"pkg"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    patch_publish_internals(monkeypatch)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    view_calls = CallRecorder('{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}')
    monkeypatch.setattr(drafts, "bash_output", view_calls)
    monkeypatch.setattr(drafts, "bash", CallRecorder())

    prerelease.main()

    assert len(view_calls.calls) == 1
