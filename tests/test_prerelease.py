from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_devkit.config import AppConfig, BuildArtifactConfig, PackageConfig, PublishConfig
from release_devkit.plan import PackagePlan, ReleasePlan
from release_devkit.verbs import release as release_module
from release_devkit.verbs.release import DEV_DRAFT_TAG, DigestEntry, ReleaseChannel

MERGE_SHA = "654321abcdef0987654321abcdef0987654321"
CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]
DRAFT_VIEW_JSON = json.dumps({"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"})


class FixedReturn:
    def __init__(self, value: object) -> None:
        self.value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.value


class CallRecorder:
    def __init__(self, return_value: object = None) -> None:
        self.return_value = return_value
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append(args)
        return self.return_value


class FakeTags:
    def __init__(self, versions: dict[str, str | None], changed: set[str]) -> None:
        self._versions = versions
        self._changed = changed

    def latest_version(self, prefix: str) -> str | None:
        return self._versions.get(prefix.removesuffix("-v"))


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
        dev: object,
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


def noop(*args: object, **kwargs: object) -> None:
    pass


def make_builds() -> list[BuildArtifactConfig]:
    return [BuildArtifactConfig(project="MyApp", platform="AndroidMobile", file="MyApp-AndroidMobile.apk")]


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
        resolved_versions={name: {} for name in publishing},
        app_last_versions=app_last_versions or {},
        app_versions={},
    )


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
    monkeypatch.setattr(release_module, "get_latest_version", tags.latest_version)


def patch_context(monkeypatch: pytest.MonkeyPatch, config: PublishConfig, draft_body: str = "") -> FakePullArtifact:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_ACTOR", "bot")
    monkeypatch.setenv("GITHUB_WORKSPACE", "/workspace")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setattr(release_module, "load_config", FixedReturn(config))
    monkeypatch.setattr(release_module, "bash_check", FixedReturn(False))
    monkeypatch.setattr(release_module, "bash", CallRecorder())

    def dispatching_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return MERGE_SHA
        if "%P" in command:
            return f"{MERGE_SHA} {CERTIFIED_SHA}\n"
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        return json.dumps({"body": draft_body, "url": "https://github.com/owner/repo/releases/untagged-abc"})

    monkeypatch.setattr(release_module, "bash_output", dispatching_bash_output)
    layers = {
        (artifact.project, artifact.platform): {f"{artifact.project}-{artifact.platform}.apk": "build content"}
        for app in config.apps.values()
        for artifact in app.builds or []
    }
    pull_artifact = FakePullArtifact(layers)
    monkeypatch.setattr(release_module, "pull_artifact", pull_artifact)
    return pull_artifact


def patch_publish_internals(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePublishRegistry, CallRecorder]:
    npm_registry = FakePublishRegistry()
    create_and_push_tag = CallRecorder()
    monkeypatch.setattr(release_module, "configure_git", noop)
    monkeypatch.setattr(release_module, "install_dotnet", noop)
    monkeypatch.setattr(release_module, "install_node", noop)
    monkeypatch.setattr(release_module, "build_registries", FixedReturn({"npm": npm_registry}))
    monkeypatch.setattr(release_module, "create_and_push_tag", create_and_push_tag)
    return npm_registry, create_and_push_tag


def run_dev_release(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[FakePublishRegistry, CallRecorder, FakePullArtifact, list[str]]:
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(release_plan))
    patch_plan_tags(monkeypatch, tags)
    pull_artifact = patch_context(monkeypatch, config)
    npm_registry, create_and_push_tag = patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(release_module, "bash", capturing_bash)

    release_module.main(channel=ReleaseChannel.DEV)

    return npm_registry, create_and_push_tag, pull_artifact, written


def test_noop_merge_publishes_nothing_but_writes_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    npm_registry, _, pull_artifact, written = run_dev_release(monkeypatch, config, make_plan(set()), tags)

    assert npm_registry.calls == []
    assert pull_artifact.calls != []
    assert written != []


def test_only_packages_changed_publishes_and_appends_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={
            "pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registry="npm", identity="pkg-id")
        },
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())
    release_plan = make_plan({"pkg"})

    npm_registry, create_and_push_tag, pull_artifact, written = run_dev_release(monkeypatch, config, release_plan, tags)

    assert len(npm_registry.calls) == 1
    assert npm_registry.calls[0]["base_version"] == "1.0.0"
    assert npm_registry.calls[0]["dev"] is True
    assert f"| pkg | 1.0.0-dev.{SHORT_SHA} |" in written[0]
    assert create_and_push_tag.calls == []
    assert pull_artifact.calls != []
    assert written != []
    assert f'<a id="sha-{SHORT_SHA}"></a>' in written[0]


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    monkeypatch.setattr(
        release_module, "compute_release_plan", FixedReturn(make_plan(set(), app_last_versions={"myapp": "1.0.0"}))
    )
    patch_plan_tags(monkeypatch, tags)
    pull_artifact = patch_context(monkeypatch, config)
    npm_registry, _ = patch_publish_internals(monkeypatch)
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(release_module, "bash", capturing_bash)

    release_module.main(channel=ReleaseChannel.DEV)

    assert npm_registry.calls == []
    assert pull_artifact.calls != []
    assert pull_artifact.calls[0][3] == f"sha-{CERTIFIED_SHA}"
    assert len(written) == 1
    assert "#### Apps" in written[0]
    assert "| App | Version | Asset |" in written[0]
    fresh_link = f"https://github.com/owner/repo/releases/download/{DEV_DRAFT_TAG}/MyApp-AndroidMobile-{SHORT_SHA}.apk"
    assert f"| myapp | 1.0.0 | [MyApp-AndroidMobile-{SHORT_SHA}.apk]({fresh_link}) |" in written[0]


def test_stages_all_apps_regardless_of_source_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        apps={
            "changed-app": make_app(
                "changed-app", [BuildArtifactConfig(project="AppA", platform="AndroidMobile", file="AppA.apk")]
            ),
            "unchanged-app": make_app(
                "unchanged-app", [BuildArtifactConfig(project="AppB", platform="AndroidMobile", file="AppB.apk")]
            ),
        }
    )
    tags = FakeTags(versions={"changed-app": "1.0.0", "unchanged-app": "2.0.0"}, changed={"changed-app"})

    _, _, pull_artifact, _ = run_dev_release(monkeypatch, config, make_plan(set()), tags)

    pulled = {(call[1], call[2]) for call in pull_artifact.calls}
    assert ("AppA", "AndroidMobile") in pulled
    assert ("AppB", "AndroidMobile") in pulled


def test_any_new_digest_appends_snapshot_section_with_all_images(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_existing = "sha256:" + "a" * 64
    digest_new = "sha256:" + "b" * 64
    manifest = {
        "zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_new, tags=["tree-1"]),
        "other-capture": DigestEntry(ref="ghcr.io/owner/repo/other-capture", digest=digest_existing, tags=["tree-2"]),
    }
    digest_data = {name: entry.model_dump() for name, entry in manifest.items()}
    digest_files = {"images-digests.json": json.dumps(digest_data)}

    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, tags)
    pull_artifact = patch_context(monkeypatch, config)
    pull_artifact.layers[("images-digests", "all")] = digest_files
    written: list[str] = []

    def capturing_bash(command: str) -> None:
        if "--notes-file" in command:
            path = command.split("--notes-file", 1)[1].strip().split()[0]
            written.append(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setattr(release_module, "bash", capturing_bash)

    release_module.main(channel=ReleaseChannel.DEV)

    assert len(written) == 1
    assert digest_new in written[0]
    assert digest_existing in written[0]
    assert f"[{SHORT_SHA}](https://github.com/owner/repo/commit/{CERTIFIED_SHA})" in written[0]


def test_snapshot_section_lists_all_packages_with_dev_and_stable_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(
        packages={
            "fresh": PackageConfig(path=Path("packages/fresh"), major_minor="1.0", registry="npm", identity="fresh-id"),
            "settled": PackageConfig(
                path=Path("packages/settled"), major_minor="1.0", registry="npm", identity="settled-id"
            ),
            "never": PackageConfig(path=Path("packages/never"), major_minor="1.0", registry="npm", identity="never-id"),
        },
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0", "settled": "2.1.0"}, changed=set())

    _, _, _, written = run_dev_release(monkeypatch, config, make_plan({"fresh"}, {"settled", "never"}), tags)

    assert len(written) == 1
    fresh_version = f"1.0.0-dev.{SHORT_SHA}"
    assert f"| fresh | {fresh_version} | [npm](https://registry.example/fresh-id/{fresh_version}) |" in written[0]
    assert "| settled | 2.1.0 | [npm](https://registry.example/settled-id/2.1.0) |" in written[0]
    assert "| never | 0.0.0 | npm |" in written[0]


def test_existing_dev_draft_viewed_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={
            "pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registry="npm", identity="pkg-id")
        },
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(make_plan({"pkg"})))
    patch_plan_tags(monkeypatch, tags)
    patch_context(monkeypatch, config)
    patch_publish_internals(monkeypatch)
    monkeypatch.setattr(release_module, "bash_check", FixedReturn(True))
    view_calls: list[str] = []

    def counting_bash_output(command: str) -> str:
        if command == "git rev-parse HEAD":
            return MERGE_SHA
        if "%P" in command:
            return f"{MERGE_SHA} {CERTIFIED_SHA}\n"
        if command.startswith("git log"):
            return "Merge PR #7: Add the thing\n"
        if command.startswith("gh release view"):
            view_calls.append(command)
            return DRAFT_VIEW_JSON
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(release_module, "bash_output", counting_bash_output)
    monkeypatch.setattr(release_module, "bash", CallRecorder())

    release_module.main(channel=ReleaseChannel.DEV)

    assert view_calls == [f"gh release view {DEV_DRAFT_TAG} --repo owner/repo --json body"]


def run_merge_identity(monkeypatch: pytest.MonkeyPatch, parents_output: str) -> FakePullArtifact:
    config = make_config(apps={"myapp": make_app()})
    monkeypatch.setattr(release_module, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, FakeTags(versions={"myapp": "1.0.0"}, changed=set()))
    pull_artifact = patch_context(monkeypatch, config)

    original_output = release_module.bash_output

    def dispatching_bash_output(command: str) -> str:
        if "%P" in command:
            return parents_output
        return str(original_output(command))

    monkeypatch.setattr(release_module, "bash_output", dispatching_bash_output)

    release_module.main(channel=ReleaseChannel.DEV)

    return pull_artifact


def test_merge_identity_resolves_the_second_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    pull_artifact = run_merge_identity(monkeypatch, f"{MERGE_SHA} {CERTIFIED_SHA}\n")

    assert pull_artifact.calls
    assert all(call[3] == f"sha-{CERTIFIED_SHA}" for call in pull_artifact.calls)


def test_merge_identity_raises_on_non_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IndexError):
        run_merge_identity(monkeypatch, f"{MERGE_SHA}\n")
