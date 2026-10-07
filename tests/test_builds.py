import json
from pathlib import Path

import pytest

from release_devkit import context as context_module
from release_devkit.builds import DigestEntry
from release_devkit.context import build_context, merge_push_context
from release_devkit.rendering import render_images_table


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


def make_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_ACTOR", "bot")
    monkeypatch.setenv("GITHUB_WORKSPACE", "/workspace")


def write_config(tmp_path: Path, content: str = "") -> Path:
    config = tmp_path / "release-devkit.yaml"
    config.write_text(content, encoding="utf-8")
    return config


def dispatching_bash_output(command: str) -> str:
    if "rev-parse" in command:
        return "cccccccccccccccccccccccccccccccccccccccc\n"
    if "%P" in command:
        return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    return ""


def single_parent_bash_output(command: str) -> str:
    if "rev-parse" in command:
        return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"


def test_merge_push_context_resolves_the_second_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make_env(monkeypatch)
    monkeypatch.setattr(context_module, "bash_output", dispatching_bash_output)

    result = merge_push_context(write_config(tmp_path))

    assert result.head == "cccccccccccccccccccccccccccccccccccccccc"
    assert result.certified == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert result.manifest is None


def test_merge_push_context_falls_back_to_head_on_non_merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make_env(monkeypatch)
    monkeypatch.setattr(context_module, "bash_output", single_parent_bash_output)

    result = merge_push_context(write_config(tmp_path))

    assert result.certified == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_build_context_manifest_is_none_when_no_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make_env(monkeypatch)

    result = build_context(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", write_config(tmp_path)
    )

    assert result.manifest is None


def test_build_context_manifest_is_none_when_build_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make_env(monkeypatch)
    monkeypatch.setattr(context_module, "build_exists", FixedReturn(False))

    result = build_context(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        write_config(tmp_path, "builds_registry: ghcr.io/owner/repo/builds\n"),
    )

    assert result.manifest is None


def test_build_context_pulls_the_sha_tag_and_parses_entries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    make_env(monkeypatch)
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

    build_exists_recorder = CallRecorder(True)
    monkeypatch.setattr(context_module, "build_exists", build_exists_recorder)
    monkeypatch.setattr(context_module, "pull_build", fake_pull_build)

    certified = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    result = build_context(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        certified,
        write_config(tmp_path, "builds_registry: ghcr.io/owner/repo/builds\n"),
    )

    assert result.manifest is not None
    assert build_exists_recorder.calls[0][3] == f"sha-{certified}"
    assert result.manifest["zed-capture"].ref == "ghcr.io/outernet-foundation/placeframe-capture-tool/zed-capture"
    assert result.manifest["zed-capture"].digest == "sha256:abc"
    assert result.manifest["zed-capture"].tags == ["tree-123", "latest"]


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
