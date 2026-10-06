from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from release_devkit import prerelease
from release_devkit.config import AppConfig, BuildArtifactConfig, BuildsConfig, PackageConfig, PublishConfig
from release_devkit.plan import PackagePlan, ReleasePlan
from release_devkit.prerelease import app_has_changes, build_prerelease_section, parse_merge_pr


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


def make_builds() -> BuildsConfig:
    return BuildsConfig(
        registry="ghcr.io/owner/repo/builds",
        artifacts=[BuildArtifactConfig(project="MyApp", platform="AndroidMobile")],
    )


def make_app(name: str = "myapp", builds: BuildsConfig | None = None) -> AppConfig:
    return AppConfig(path=Path(f"apps/{name}"), major_minor="1.0", builds=builds or make_builds())


def make_config(
    packages: dict[str, PackageConfig] | None = None,
    apps: dict[str, AppConfig] | None = None,
) -> PublishConfig:
    return PublishConfig(ci_workflow="integrate.yml", packages=packages or {}, apps=apps or {})


def make_plan(publishing: set[str]) -> ReleasePlan:
    plans = {name: PackagePlan(name=name, publish=True, version="1.0.0", last_version=None) for name in publishing}
    return ReleasePlan(
        plans=plans,
        publishing=publishing,
        resolved_versions={},
        app_last_versions={},
        app_versions={},
    )


def null_ci_step(label: str) -> object:
    return nullcontext()


def noop(*args: object, **kwargs: object) -> None:
    pass


def patch_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_ACTOR": "bot",
        "GITHUB_TOKEN": "token",
        "GITHUB_RUN_ID": "42",
        "GITHUB_WORKSPACE": "/workspace",
        "GITHUB_STEP_SUMMARY": "",
    }.items():
        monkeypatch.setenv(key, value)


def run_prerelease(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[CallRecorder, CallRecorder, CallRecorder, CallRecorder]:
    patch_environment(monkeypatch)
    monkeypatch.setattr(prerelease, "load_config", FixedReturn(config))
    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(release_plan))
    monkeypatch.setattr(prerelease, "GitTags", FixedReturn(tags))
    monkeypatch.setattr(prerelease, "ci_step", null_ci_step)
    monkeypatch.setattr(prerelease, "append_line", noop)
    monkeypatch.setattr(prerelease, "configure_git", noop)
    monkeypatch.setattr(prerelease, "free_disk_space", noop)
    monkeypatch.setattr(prerelease, "install_dotnet", noop)
    monkeypatch.setattr(prerelease, "install_node", noop)
    build_registries = CallRecorder({})
    monkeypatch.setattr(prerelease, "build_registries", build_registries)
    monkeypatch.setattr(prerelease, "matched_ci_run_number", FixedReturn("42"))
    pull_assets = CallRecorder([])
    monkeypatch.setattr(prerelease, "pull_build_assets", pull_assets)
    monkeypatch.setattr(prerelease, "stage_draft_assets", CallRecorder([]))
    ensure_draft = CallRecorder()
    monkeypatch.setattr(prerelease, "ensure_draft_release", ensure_draft)
    monkeypatch.setattr(prerelease, "upload_draft_assets", CallRecorder())
    monkeypatch.setattr(prerelease, "parse_merge_pr", FixedReturn(None))
    append_section = CallRecorder()
    monkeypatch.setattr(prerelease, "append_draft_section", append_section)
    monkeypatch.setattr(prerelease, "emit_draft_backlink", CallRecorder())

    prerelease.main()

    return build_registries, pull_assets, ensure_draft, append_section


def test_app_has_changes_returns_true_when_never_released() -> None:
    tags = FakeTags(versions={"myapp": None}, changed=set())

    assert app_has_changes(tags, "myapp", make_app()) is True


def test_app_has_changes_returns_true_when_source_changed() -> None:
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    assert app_has_changes(tags, "myapp", make_app()) is True


def test_app_has_changes_returns_false_when_source_unchanged() -> None:
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    assert app_has_changes(tags, "myapp", make_app()) is False


def test_nothing_changed_returns_without_publishing_or_drafting(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    build_registries, pull_assets, ensure_draft, append_section = run_prerelease(
        monkeypatch, config, make_plan(set()), tags
    )

    assert build_registries.calls == []
    assert pull_assets.calls == []
    assert ensure_draft.calls == []
    assert append_section.calls == []


def test_only_packages_changed_publishes_and_appends_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    build_registries, pull_assets, ensure_draft, append_section = run_prerelease(
        monkeypatch, config, make_plan({"pkg"}), tags
    )

    assert build_registries.calls != []
    assert pull_assets.calls == []
    assert ensure_draft.calls == []
    assert append_section.calls != []


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    build_registries, pull_assets, ensure_draft, append_section = run_prerelease(
        monkeypatch, config, make_plan(set()), tags
    )

    assert build_registries.calls == []
    assert pull_assets.calls != []
    assert ensure_draft.calls != []
    assert append_section.calls != []


def test_dev_draft_surfaces_only_changed_apps(monkeypatch: pytest.MonkeyPatch) -> None:
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

    _, pull_assets, _, _ = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert len(pull_assets.calls) == 1
    draft_config = pull_assets.calls[0][0]
    assert isinstance(draft_config, PublishConfig)
    assert set(draft_config.apps) == {"changed-app"}


def test_build_prerelease_section_renders_packages_assets_and_pr_link() -> None:
    published = [("pypi", "placeframe-common", "0.1.0.dev42")]
    staged_assets = [("MyApp-run-42.apk", Path("/tmp/MyApp-run-42.apk"))]

    section = build_prerelease_section(published, staged_assets, "owner/repo", "42", (15, "Add feature"))

    assert "### [Run #42]" in section
    assert "https://github.com/owner/repo/actions/runs/42" in section
    assert "[PR #15: Add feature]" in section
    assert "https://github.com/owner/repo/pull/15" in section
    assert "| placeframe-common | 0.1.0.dev42 |" in section
    assert "[pypi](https://pypi.org/project/placeframe-common/0.1.0.dev42)" in section
    assert "[MyApp-run-42.apk]" in section
    assert "https://github.com/owner/repo/releases/download/dev-builds/MyApp-run-42.apk" in section


def test_build_prerelease_section_omits_pr_link_when_none() -> None:
    section = build_prerelease_section([], [], "owner/repo", "42", None)

    assert "### [Run #42]" in section
    assert "PR #" not in section


def test_parse_merge_pr_extracts_pr_number_and_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prerelease, "bash_output", FixedReturn("Merge PR #42: Add feature X\n"))

    result = parse_merge_pr("abc123")

    assert result == (42, "Add feature X")


def test_parse_merge_pr_returns_none_for_non_merge_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prerelease, "bash_output", FixedReturn("Just a regular commit\n"))

    result = parse_merge_pr("abc123")

    assert result is None
