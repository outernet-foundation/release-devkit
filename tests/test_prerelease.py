from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from release_devkit.verbs import prerelease
from release_devkit import drafts
from release_devkit.config import AppConfig, BuildArtifactConfig, BuildsConfig, PackageConfig, PublishConfig
from release_devkit.builds import DigestEntry
from release_devkit.plan import PackagePlan, ReleasePlan


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


def patch_common(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(prerelease, "ci_step", null_ci_step)
    monkeypatch.setattr(prerelease, "setup_publishing_environment", noop)
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash", CallRecorder())
    monkeypatch.setattr(
        prerelease, "matched_ci_run_number", FixedReturn(("42", "https://github.com/owner/repo/actions/runs/99"))
    )
    monkeypatch.setattr(prerelease, "pull_digest_manifest", FixedReturn(None))
    pull_assets = CallRecorder([])
    monkeypatch.setattr(drafts, "pull_build_assets", pull_assets)
    monkeypatch.setattr(prerelease, "bash_output", FixedReturn("Not a merge commit\n"))
    return pull_assets


def run_prerelease(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[CallRecorder, CallRecorder, CallRecorder]:
    monkeypatch.setattr(prerelease, "load_config", FixedReturn(config))
    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(release_plan))
    monkeypatch.setattr(prerelease, "GitTags", FixedReturn(tags))
    pull_assets = patch_common(monkeypatch)
    publish_packages = CallRecorder([])
    monkeypatch.setattr(prerelease, "publish_packages", publish_packages)
    append_section = CallRecorder()
    monkeypatch.setattr(prerelease, "append_draft_section", append_section)

    prerelease.main(
        repository="owner/repo",
        sha="abc123def456",
        actor="bot",
        workspace="/workspace",
        run_id="42",
        step_summary="",
    )

    return publish_packages, pull_assets, append_section


def test_nothing_changed_returns_without_publishing_or_drafting(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    publish_packages, pull_assets, append_section = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert publish_packages.calls == []
    assert pull_assets.calls == []
    assert append_section.calls == []


def test_only_packages_changed_publishes_and_appends_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    publish_packages, pull_assets, append_section = run_prerelease(monkeypatch, config, make_plan({"pkg"}), tags)

    assert publish_packages.calls != []
    assert pull_assets.calls == []
    assert append_section.calls != []


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    publish_packages, pull_assets, append_section = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert publish_packages.calls == []
    assert pull_assets.calls != []
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

    _, pull_assets, _ = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert len(pull_assets.calls) == 1
    draft_config = pull_assets.calls[0][0]
    assert isinstance(draft_config, PublishConfig)
    assert set(draft_config.apps) == {"changed-app"}


def test_only_new_image_digests_appends_section_without_publishing(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_existing = "sha256:" + "a" * 64
    digest_new = "sha256:" + "b" * 64
    manifest = {
        "zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_new, tags=["tree-1"]),
        "other-capture": DigestEntry(ref="ghcr.io/owner/repo/other-capture", digest=digest_existing, tags=["tree-2"]),
    }

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(prerelease, "load_config", FixedReturn(config))
    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan(set())))
    monkeypatch.setattr(prerelease, "GitTags", FixedReturn(tags))
    monkeypatch.setattr(prerelease, "ci_step", null_ci_step)
    monkeypatch.setattr(
        prerelease, "matched_ci_run_number", FixedReturn(("42", "https://github.com/owner/repo/actions/runs/99"))
    )
    monkeypatch.setattr(prerelease, "pull_digest_manifest", FixedReturn(manifest))
    monkeypatch.setattr(prerelease, "bash_check", FixedReturn(True))

    def mock_bash_output(command: str) -> str:
        if "git log" in command:
            return "Not a merge commit\n"
        return f"`{digest_existing}`"

    monkeypatch.setattr(prerelease, "bash_output", mock_bash_output)
    pull_assets = CallRecorder([])
    monkeypatch.setattr(drafts, "pull_build_assets", pull_assets)
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    sections: list[str] = []

    def capture_section(tag: str, repository: str, anchor: str, section: str) -> None:
        sections.append(section)

    monkeypatch.setattr(prerelease, "append_draft_section", capture_section)

    prerelease.main(
        repository="owner/repo",
        sha="abc123def456",
        actor="bot",
        workspace="/workspace",
        run_id="42",
        step_summary="",
    )

    assert pull_assets.calls == []
    assert len(sections) == 1
    assert digest_new in sections[0]
    assert digest_existing not in sections[0]
