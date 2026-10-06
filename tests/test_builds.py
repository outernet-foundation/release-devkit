import json
from pathlib import Path

import pytest
import typer

from release_devkit import builds
from release_devkit.config import AppConfig, BuildArtifactConfig, BuildsConfig, PublishConfig
from release_devkit.builds import (
    DigestEntry,
    builds_registry_of,
    matched_ci_run_number,
    pull_digest_manifest,
)
from release_devkit.rendering import render_images_table


class SequentialOutputs:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        return self.outputs.pop(0)


class FixedReturn:
    def __init__(self, value: object) -> None:
        self._value = value

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self._value


def patch_recorder(monkeypatch: pytest.MonkeyPatch, outputs: list[str]) -> SequentialOutputs:
    recorder = SequentialOutputs(outputs)
    monkeypatch.setattr("release_devkit.builds.bash_output", recorder)
    return recorder


def run_result_json(run_number: int, html_url: str = "https://github.com/owner/repo/actions/runs/99") -> str:
    return json.dumps({"run_number": run_number, "html_url": html_url})


def test_matched_ci_run_number_queries_resolved_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_recorder(monkeypatch, ["def456\n", run_result_json(42) + "\n"])

    result = matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")

    assert result == ("42", "https://github.com/owner/repo/actions/runs/99")
    assert ".parents[1].sha // .sha" in recorder.commands[0]
    assert "head_sha=def456" in recorder.commands[1]
    assert "workflows/integrate.yml/runs" in recorder.commands[1]


def test_matched_ci_run_number_falls_back_to_promoted_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_recorder(monkeypatch, ["abc1234\n", run_result_json(7) + "\n"])

    result = matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")

    assert result == ("7", "https://github.com/owner/repo/actions/runs/99")
    assert "head_sha=abc1234" in recorder.commands[1]


def test_matched_ci_run_number_exits_when_no_run(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_recorder(monkeypatch, ["abc1234\n", '{"run_number":null,"html_url":null}\n'])

    with pytest.raises(typer.Exit) as exit_info:
        matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")
    assert exit_info.value.exit_code == 1


def test_builds_registry_of_returns_first_builds_registry() -> None:
    config = PublishConfig(
        ci_workflow="integrate.yml",
        apps={
            "a": AppConfig(
                path=Path("apps/a"),
                major_minor="1.0",
                builds=BuildsConfig(
                    registry="ghcr.io/owner/repo/builds",
                    artifacts=[BuildArtifactConfig(project="A", platform="p")],
                ),
            )
        },
    )

    assert builds_registry_of(config) == "ghcr.io/owner/repo/builds"


def test_builds_registry_of_returns_none_when_no_builds() -> None:
    config = PublishConfig(ci_workflow="integrate.yml", apps={"a": AppConfig(path=Path("apps/a"), major_minor="1.0")})

    assert builds_registry_of(config) is None


def test_pull_digest_manifest_returns_none_when_no_registry() -> None:
    assert pull_digest_manifest(None, "42", "", "") is None


def test_pull_digest_manifest_returns_none_when_build_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builds, "build_exists", FixedReturn(False))

    assert pull_digest_manifest("ghcr.io/owner/repo/builds", "42", "", "") is None


def test_pull_digest_manifest_parses_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_data = {
        "zed-capture": {
            "ref": "ghcr.io/outernet-foundation/placeframe-capture-tool/zed-capture",
            "digest": "sha256:abc",
            "tags": ["tree-123", "latest"],
        }
    }

    def fake_pull_build(
        registry: str, project: str, platform: str, tag: str, target_directory: Path, **kwargs: object
    ) -> None:
        (target_directory / "images-digests.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    monkeypatch.setattr(builds, "build_exists", FixedReturn(True))
    monkeypatch.setattr(builds, "pull_build", fake_pull_build)

    result = pull_digest_manifest("ghcr.io/owner/repo/builds", "42", "", "")

    assert result is not None
    assert "zed-capture" in result
    assert result["zed-capture"].ref == "ghcr.io/outernet-foundation/placeframe-capture-tool/zed-capture"
    assert result["zed-capture"].digest == "sha256:abc"
    assert result["zed-capture"].tags == ["tree-123", "latest"]


def test_render_images_table_links_tree_tag_to_ghcr_url() -> None:
    manifest = {
        "zed-capture": DigestEntry(
            ref="ghcr.io/outernet-foundation/placeframe-capture-tool/zed-capture",
            digest="sha256:abc123",
            tags=["tree-123", "latest"],
        )
    }

    lines = render_images_table(manifest)

    assert lines[0] == "| Image | Tag | Digest |"
    assert any(
        "tree-123" in line
        and "github.com/orgs/outernet-foundation/packages/container/placeframe-capture-tool%2Fzed-capture" in line
        for line in lines
    )
    assert any("`sha256:abc123`" in line for line in lines)
