from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from release_devkit import drafts
from release_devkit import plan as plan_module
from release_devkit.config import AppConfig, BuildArtifactConfig, PackageConfig, PublishConfig, Settings
from release_devkit.builds import DigestEntry
from release_devkit.context import VerbContext
from release_devkit.plan import PackagePlan, ReleasePlan
from release_devkit.rendering import PackageRow, render_draft_section
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


CERTIFIED_SHA = "abcdef1234567890abcdef1234567890abcdef12"
SHORT_SHA = CERTIFIED_SHA[:12]
MERGE_SHA = "654321abcdef0987654321abcdef0987654321"


def noop(*args: object, **kwargs: object) -> None:
    pass


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTags) -> None:
    monkeypatch.setattr(plan_module, "latest_version", tags.latest_version)
    monkeypatch.setattr(plan_module, "latest_version_in_line", tags.latest_version_in_line)
    monkeypatch.setattr(plan_module, "has_changes_since", tags.has_changes_since)


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


def patch_common(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    manifest: dict[str, DigestEntry] | None = None,
) -> CallRecorder:
    monkeypatch.setattr(prerelease, "merge_push_context", FixedReturn(make_context(config, manifest)))
    monkeypatch.setattr(drafts, "ci_step", null_ci_step)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(False))
    monkeypatch.setattr(drafts, "bash", CallRecorder())
    monkeypatch.setattr(
        drafts,
        "bash_output",
        FixedReturn('{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}'),
    )
    monkeypatch.setattr(prerelease, "merge_push_context", FixedReturn(make_context(config, manifest)))
    pull_assets = CallRecorder([])
    monkeypatch.setattr(drafts, "pull_build_assets", pull_assets)
    monkeypatch.setattr(prerelease, "bash_output", FixedReturn("Merge PR #7: Add the thing\n"))
    return pull_assets


def run_prerelease(
    monkeypatch: pytest.MonkeyPatch,
    config: PublishConfig,
    release_plan: ReleasePlan,
    tags: FakeTags,
) -> tuple[CallRecorder, CallRecorder, list[tuple[str, str]]]:
    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(release_plan))
    patch_plan_tags(monkeypatch, tags)
    pull_assets = patch_common(monkeypatch, config)
    publish_packages = CallRecorder([])
    monkeypatch.setattr(prerelease, "publish_packages", publish_packages)
    upserts: list[tuple[str, str]] = []

    def record_upsert(
        instance: drafts.DraftRelease,
        anchor: str,
        heading_fragments: list[str],
        staged: list[tuple[str, Path]],
        manifest: dict[str, DigestEntry] | None,
        packages: list[PackageRow] | None,
    ) -> None:
        upserts.append((anchor, render_draft_section(heading_fragments, None, manifest, packages)))

    monkeypatch.setattr(drafts.DraftRelease, "upsert_section", record_upsert)

    prerelease.main()

    return publish_packages, pull_assets, upserts


def test_nothing_changed_returns_without_publishing_or_drafting(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    publish_packages, pull_assets, upserts = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert publish_packages.calls == []
    assert pull_assets.calls == []
    assert upserts == []


def test_only_packages_changed_publishes_and_appends_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())
    release_plan = make_plan({"pkg"})

    publish_packages, pull_assets, upserts = run_prerelease(monkeypatch, config, release_plan, tags)

    assert publish_packages.calls != []
    assert pull_assets.calls == []
    assert upserts != []
    assert upserts[0][0] == f"sha-{SHORT_SHA}"
    strategy = publish_packages.calls[0][3]
    assert isinstance(strategy, prerelease.DevStrategy)
    assert strategy.package_version("npm", release_plan.plans["pkg"]) == f"1.0.0-dev.{SHORT_SHA}"


def test_only_apps_changed_surfaces_draft_but_skips_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed={"myapp"})

    publish_packages, pull_assets, upserts = run_prerelease(monkeypatch, config, make_plan(set()), tags)

    assert publish_packages.calls == []
    assert pull_assets.calls != []
    assert pull_assets.calls[0][1] == CERTIFIED_SHA
    assert upserts != []


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


def test_any_new_digest_appends_snapshot_section_with_all_images(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_existing = "sha256:" + "a" * 64
    digest_new = "sha256:" + "b" * 64
    manifest = {
        "zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_new, tags=["tree-1"]),
        "other-capture": DigestEntry(ref="ghcr.io/owner/repo/other-capture", digest=digest_existing, tags=["tree-2"]),
    }

    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan(set())))
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
    sections: list[str] = []

    def record_upsert(
        instance: drafts.DraftRelease,
        anchor: str,
        heading_fragments: list[str],
        staged: list[tuple[str, Path]],
        manifest: dict[str, DigestEntry] | None,
        packages: list[PackageRow] | None,
    ) -> None:
        sections.append(render_draft_section(heading_fragments, None, manifest, packages))

    monkeypatch.setattr(drafts.DraftRelease, "upsert_section", record_upsert)

    prerelease.main()

    assert len(sections) == 1
    assert digest_new in sections[0]
    assert digest_existing in sections[0]
    assert f"[{SHORT_SHA}](https://github.com/owner/repo/commit/{CERTIFIED_SHA})" in sections[0]


def test_unchanged_images_only_run_skips_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    digest_known = "sha256:" + "a" * 64
    manifest = {"zed-capture": DigestEntry(ref="ghcr.io/owner/repo/zed-capture", digest=digest_known, tags=["tree-1"])}

    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan(set())))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config, manifest=manifest)
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    draft_body = f"| zed-capture | tree-0 | `{digest_known}` |"
    monkeypatch.setattr(
        drafts,
        "bash_output",
        FixedReturn(json.dumps({"body": draft_body, "url": "https://github.com/owner/repo/releases/untagged-abc"})),
    )
    upserts: list[tuple[str, str]] = []

    def record_upsert(
        instance: drafts.DraftRelease,
        anchor: str,
        heading_fragments: list[str],
        staged: list[tuple[str, Path]],
        manifest: dict[str, DigestEntry] | None,
        packages: list[PackageRow] | None,
    ) -> None:
        upserts.append((anchor, render_draft_section(heading_fragments, None, manifest, packages)))

    monkeypatch.setattr(drafts.DraftRelease, "upsert_section", record_upsert)

    prerelease.main()

    assert upserts == []


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

    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan({"fresh"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    monkeypatch.setattr(prerelease, "publish_packages", CallRecorder([("npm", "fresh-id", "1.0.1-dev.abcdef123456")]))
    upserts: list[tuple[str, str]] = []

    def record_upsert(
        instance: drafts.DraftRelease,
        anchor: str,
        heading_fragments: list[str],
        staged: list[tuple[str, Path]],
        manifest: dict[str, DigestEntry] | None,
        packages: list[PackageRow] | None,
    ) -> None:
        upserts.append((anchor, render_draft_section(heading_fragments, None, manifest, packages)))

    monkeypatch.setattr(drafts.DraftRelease, "upsert_section", record_upsert)

    prerelease.main()

    assert len(upserts) == 1
    section = upserts[0][1]
    assert "| fresh | 1.0.1-dev.abcdef123456 |" in section
    assert "| settled | 2.1.0 |" in section


def test_snapshot_section_carries_forward_unchanged_app_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(apps={"myapp": make_app()})
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    old_asset = "MyApp-AndroidMobile-999999999999.apk"
    old_link = f"- [{old_asset}](https://github.com/owner/repo/releases/download/dev-builds/{old_asset})"
    draft_body = f'<a id="sha-999999999999"></a>\n### Old\n{old_link}'

    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan({"pkg"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    monkeypatch.setattr(prerelease, "publish_packages", CallRecorder([]))
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
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

    assert written
    section = written[0].split(f'<a id="sha-{SHORT_SHA}"></a>', 1)[1].split('<a id="sha-999999999999"></a>', 1)[0]
    assert old_link in section


def test_existing_dev_draft_viewed_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        packages={"pkg": PackageConfig(path=Path("packages/pkg"), major_minor="1.0", registries={})},
        apps={"myapp": make_app()},
    )
    tags = FakeTags(versions={"myapp": "1.0.0"}, changed=set())

    monkeypatch.setattr(prerelease, "compute_release_plan", FixedReturn(make_plan({"pkg"})))
    patch_plan_tags(monkeypatch, tags)
    patch_common(monkeypatch, config)
    monkeypatch.setattr(prerelease, "publish_packages", CallRecorder([]))
    monkeypatch.setattr(drafts, "bash_check", FixedReturn(True))
    view_calls = CallRecorder('{"body": "", "url": "https://github.com/owner/repo/releases/untagged-abc"}')
    monkeypatch.setattr(drafts, "bash_output", view_calls)
    monkeypatch.setattr(drafts, "bash", CallRecorder())

    prerelease.main()

    assert len(view_calls.calls) == 1
