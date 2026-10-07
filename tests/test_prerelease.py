from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_devkit import drafts
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

    def url(self, identity: object, version: object) -> str:
        return f"https://registry.example/{identity}/{version}"

    def publish(
        self,
        path: object,
        base_version: object,
        resolved_dependencies: object,
        dev: bool,
        short_sha: object,
    ) -> object:
        self.calls.append({
            "path": path,
            "base_version": base_version,
            "resolved_dependencies": resolved_dependencies,
            "dev": dev,
            "short_sha": short_sha,
        })
        return f"{base_version}-dev.{short_sha}" if dev else base_version


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


def make_plan(
    publishing: set[str],
    unchanged: set[str] | None = None,
    app_last_versions: dict[str, str | None] | None = None,
) -> ReleasePlan:
    names = publishing | (unchanged or set())
    plans = {
        name: PackagePlan(name=name, publish=name in publishing, version="1.0.0", last_version=None) for name in names
    }
    return ReleasePlan(
        plans=plans,
        publishing=publishing,
        publishing_registries=set(),
        resolved_versions={name: {} for name in publishing},
        app_last_versions=app_last_versions or {},
        app_versions={},
    )


CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]
MERGE_SHA = "654321abcdef0987654321abcdef0987654321"


def noop(*args: object, **kwargs: object) -> None:
    pass


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
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


class FakePullBuild:
    def __init__(self, layers: dict[tuple[str, str], list[str]]) -> None:
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
    ) -> None:
        self.calls.append((builds_registry, project, platform, tag, target))
        target.mkdir(parents=True, exist_ok=True)
        for file_name in self.layers[(project, platform)]:
            (target / file_name).write_text("build content", encoding="utf-8")


def patch_pull_build(monkeypatch: pytest.MonkeyPatch, layers: dict[tuple[str, str], list[str]]) -> FakePullBuild:
    pull_build = FakePullBuild(layers)
    monkeypatch.setattr(drafts, "pull_build", pull_build)
    return pull_build


def patch_common(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    manifest: dict[str, DigestEntry] | None = None,
) -> FakePullBuild:
    monkeypatch.setattr(drafts, "build_context", FixedReturn(make_context(config, manifest)))
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash", CallRecorder())

    def dispatching_bash_output(command: str) -> str:
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        return '{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}'

    monkeypatch.setattr(drafts, "bash_output", dispatching_bash_output)
    layers = {
        (artifact.project, artifact.platform): [f"{artifact.project}.apk"]
        for app in config.apps.values()
        for artifact in app.builds or []
    }
    pull_build = patch_pull_build(monkeypatch, layers)
    return pull_build


def patch_publish_internals(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePublishRegistry, CallRecorder]:
    npm_registry = FakePublishRegistry()
    create_and_push_tag = CallRecorder()
    monkeypatch.setattr(drafts, "configure_git", noop)
    monkeypatch.setattr(drafts, "install_dotnet", noop)
    monkeypatch.setattr(drafts, "install_node", noop)
    monkeypatch.setattr(drafts, "build_registries", FixedReturn({"npm": npm_registry}))
    monkeypatch.setattr(drafts, "create_and_push_tag", create_and_push_tag)
    return npm_registry, create_and_push_tag


def run_prerelease(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[FakePublishRegistry, CallRecorder, FakePullBuild, list[str]]:
    monkeypatch.setattr(drafts, "compute_release_plan", FixedReturn(release_plan))
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
    assert npm_registry.calls[0]["base_version"] == "1.0.0"
    assert npm_registry.calls[0]["dev"] is True
    assert f"| pkg | 1.0.0-dev.{SHORT_SHA} |" in written[0]
    assert create_and_push_tag.calls == []
    assert pull_assets.calls != []
    assert written != []
    assert f'<a id="sha-{SHORT_SHA}"></a>' in written[0]


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    monkeypatch.setattr(
        drafts, "compute_release_plan", FixedReturn(make_plan(set(), app_last_versions={"myapp": "1.0.0"}))
    )
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    pull_build = patch_pull_build(monkeypatch, {("MyApp", "AndroidMobile"): ["MyApp-AndroidMobile.apk"]})
    npm_registry, _ = patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(drafts, "bash", capturing_bash)

    prerelease.main()

    assert npm_registry.calls == []
    assert pull_build.calls != []
    assert pull_build.calls[0][3] == f"sha-{CERTIFIED_SHA}"
    assert len(written) == 1
    assert "#### Apps" in written[0]
    assert "| App | Version | Asset |" in written[0]
    fresh_link = f"https://github.com/owner/repo/releases/download/dev-builds/MyApp-AndroidMobile-{SHORT_SHA}.apk"
    assert f"| myapp | 1.0.0 | [MyApp-AndroidMobile-{SHORT_SHA}.apk]({fresh_link}) |" in written[0]


def test_stages_all_apps_regardless_of_source_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        apps={
            "changed-app": make_app("changed-app", [BuildArtifactConfig(project="AppA", platform="AndroidMobile")]),
            "unchanged-app": make_app("unchanged-app", [BuildArtifactConfig(project="AppB", platform="AndroidMobile")]),
        }
    )
    tags = FakeTags(
        versions={"changed-app": "1.0.0", "unchanged-app": "2.0.0"},
        changed={"changed-app"},
    )

    _, _, pull_build, _ = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert {(call[1], call[2]) for call in pull_build.calls} == {
        ("AppA", "AndroidMobile"),
        ("AppB", "AndroidMobile"),
    }


def test_any_new_digest_appends_snapshot_section_with_all_images(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_existing = "sha256:" + "a" * 64
    digest_new = "sha256:" + "b" * 64
    manifest = {
        "zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_new, tags=["tree-1"]),
        "other-capture": DigestEntry(ref="ghcr.io/owner/repo/other-capture", digest=digest_existing, tags=["tree-2"]),
    }

    monkeypatch.setattr(drafts, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config, manifest=manifest)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    draft_body = (
        f"#### Built images\n| Image | Tag | Digest |\n|---|---|---|\n| other-capture | tree-2 | `{digest_existing}` |"
    )

    def dispatching_bash_output(command: str) -> str:
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        return json.dumps({"body": draft_body, "url": "https://github.com/owner/repo/releases/untagged-abc"})

    monkeypatch.setattr(drafts, "bash_output", dispatching_bash_output)
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
            "never": PackageConfig(path=Path("packages/never"), major_minor="1.0", registries={"npm": "never-id"}),
        },
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0", "settled": "2.1.0"}, changed=set())

    monkeypatch.setattr(drafts, "compute_release_plan", FixedReturn(make_plan({"fresh"}, {"settled", "never"})))
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
    assert "| never | 0.0.0 | npm |" in written[0]


def test_existing_dev_draft_viewed_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    monkeypatch.setattr(drafts, "compute_release_plan", FixedReturn(make_plan({"pkg"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    patch_publish_internals(monkeypatch)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    view_calls = CallRecorder('{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}')

    def counting_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return MERGE_SHA
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        return str(view_calls(command))

    monkeypatch.setattr(drafts, "bash_output", counting_bash_output)
    monkeypatch.setattr(drafts, "bash", CallRecorder())

    prerelease.main()

    assert len(view_calls.calls) == 1


def run_merge_identity(monkeypatch: pytest.MonkeyPatch, parents_output: str) -> CallRecorder:
    config = make_config(apps={"myapp": make_app()})
    monkeypatch.setattr(drafts, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed=set()))
    build_context = CallRecorder(make_context(config))
    monkeypatch.setattr(drafts, "build_context", build_context)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash", CallRecorder())

    def dispatching_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return MERGE_SHA
        if "%P" in command:
            return parents_output
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        return '{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}'

    monkeypatch.setattr(drafts, "bash_output", dispatching_bash_output)
    patch_pull_build(monkeypatch, {("MyApp", "AndroidMobile"): ["MyApp.apk"]})

    prerelease.main()

    return build_context


def test_merge_identity_resolves_the_second_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    build_context = run_merge_identity(monkeypatch, f"{MERGE_SHA} {CERTIFIED_SHA}\n")

    assert build_context.calls[0][:2] == (MERGE_SHA, CERTIFIED_SHA)


def test_merge_identity_falls_back_to_head_on_non_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    build_context = run_merge_identity(monkeypatch, f"{MERGE_SHA}\n")

    assert build_context.calls[0][:2] == (MERGE_SHA, MERGE_SHA)
