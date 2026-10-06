from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from tempfile import mkdtemp

import pytest

from release_devkit import draft_releases
from release_devkit.config import AppConfig, BuildArtifactConfig, BuildsConfig, PublishConfig
from release_devkit.create_release import pull_build_assets
from release_devkit.draft_releases import (
    append_draft_section,
    delete_draft_release,
    emit_draft_backlink,
    emit_draft_summary,
    ensure_draft_release,
    replace_or_prepend_section,
    stage_draft_assets,
    update_pr_draft,
    upload_draft_assets,
)


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
        "GITHUB_STEP_SUMMARY": "",
    }.items():
        monkeypatch.setenv(key, value)


def patch_bash(monkeypatch: pytest.MonkeyPatch, check_returns: object = False) -> BashLog:
    monkeypatch.setattr(draft_releases, "ci_step", null_ci_step)
    monkeypatch.setattr(draft_releases, "bash_check", FixedReturn(check_returns))
    bash_log = BashLog()
    monkeypatch.setattr(draft_releases, "bash", bash_log)
    return bash_log


def test_pull_build_assets_returns_empty_when_no_builds() -> None:
    result = pull_build_assets(make_empty_config(), "42", "", "")
    assert result == []


def test_stage_draft_assets_uses_configured_name_stem() -> None:
    source = make_source_file("original.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile", name="MyApp-AndroidMobile.apk")

    staged = stage_draft_assets([(artifact, source)], "42")

    assert len(staged) == 1
    name, path = staged[0]
    assert name == "MyApp-AndroidMobile-run-42.apk"
    assert path.is_file()


def test_stage_draft_assets_uses_source_stem_when_name_unset() -> None:
    source = make_source_file("app.apk")
    artifact = BuildArtifactConfig(project="MyApp", platform="AndroidMobile")

    staged = stage_draft_assets([(artifact, source)], "42")

    assert len(staged) == 1
    assert staged[0][0] == "app-run-42.apk"


def test_ensure_draft_release_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)

    ensure_draft_release("pr-7", "owner/repo", "abc123")

    assert any("gh release create pr-7" in command for command in bash_log.commands)
    assert any("--draft" in command for command in bash_log.commands)
    assert any("--target abc123" in command for command in bash_log.commands)


def test_ensure_draft_release_skips_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=True)

    ensure_draft_release("pr-7", "owner/repo", "abc123")

    assert not bash_log.commands


def test_upload_draft_assets_uses_clobber(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch)
    source = make_source_file("asset.apk")

    upload_draft_assets("pr-7", "owner/repo", [("asset-run-42.apk", source)])

    assert any("gh release upload pr-7" in command and "--clobber" in command for command in bash_log.commands)


def test_emit_draft_summary_writes_download_links(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.md"
    source = make_source_file("asset.apk")

    emit_draft_summary(str(summary_path), "pr-7", "owner/repo", [("MyApp-run-42.apk", source)])

    content = summary_path.read_text(encoding="utf-8")
    assert "https://github.com/owner/repo/releases/download/pr-7/MyApp-run-42.apk" in content
    assert "[MyApp-run-42.apk]" in content


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
    monkeypatch.setattr(draft_releases, "load_config", FixedReturn(make_build_config()))
    monkeypatch.setattr(draft_releases, "pull_build_assets", FixedReturn([(artifact, source)]))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft(pr_number=7, run_number=42)

    assert any("pr-7" in command for command in bash_log.commands)
    assert any("gh release upload pr-7" in command and "--clobber" in command for command in bash_log.commands)
    assert any("MyApp-AndroidMobile-run-42.apk" in command for command in bash_log.commands)


def test_update_pr_draft_noop_on_empty_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_verb_environment(monkeypatch)
    monkeypatch.setattr(draft_releases, "load_config", FixedReturn(make_empty_config()))
    bash_log = patch_bash(monkeypatch, check_returns=False)

    update_pr_draft(pr_number=7, run_number=42)

    assert not bash_log.commands


def test_replace_or_prepend_section_prepends_to_empty_body() -> None:
    result = replace_or_prepend_section("", "run-42", "### Heading")

    assert result == '<a id="run-42"></a>\n### Heading\n'


def test_replace_or_prepend_section_prepends_newest_first() -> None:
    body = '<a id="run-42"></a>\n### Old'

    result = replace_or_prepend_section(body, "run-43", "### New")

    assert result.startswith('<a id="run-43"></a>\n### New')
    assert '<a id="run-42"></a>\n### Old' in result


def test_replace_or_prepend_section_replaces_existing_anchor() -> None:
    body = '<a id="run-42"></a>\n### Old\n\n| pkg |'

    result = replace_or_prepend_section(body, "run-42", "### Updated")

    assert "### Old" not in result
    assert '<a id="run-42"></a>\n### Updated' in result


def test_append_draft_section_writes_notes_file(monkeypatch: pytest.MonkeyPatch) -> None:
    bash_log = patch_bash(monkeypatch, check_returns=False)
    monkeypatch.setattr(draft_releases, "bash_output", FixedReturn(""))

    append_draft_section("dev-builds", "owner/repo", "abc123", "run-42", "### Heading")

    assert any("gh release edit dev-builds" in command and "--notes-file" in command for command in bash_log.commands)


def test_emit_draft_backlink_writes_anchor_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary_path = tmp_path / "summary.md"
    monkeypatch.setattr(
        draft_releases, "bash_output", FixedReturn("https://github.com/owner/repo/releases/tag/untagged-abc")
    )

    emit_draft_backlink(str(summary_path), "dev-builds", "owner/repo", "run-42")

    content = summary_path.read_text(encoding="utf-8")
    assert "https://github.com/owner/repo/releases/tag/untagged-abc#run-42" in content
