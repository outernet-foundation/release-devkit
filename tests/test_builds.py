import json
from pathlib import Path

import pytest

from release_devkit import builds
from release_devkit.builds import (
    DigestEntry,
    certified_sha,
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


class CallRecorder:
    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append(args)
        return self._return_value


def patch_recorder(monkeypatch: pytest.MonkeyPatch, outputs: list[str]) -> SequentialOutputs:
    recorder = SequentialOutputs(outputs)
    monkeypatch.setattr("release_devkit.builds.bash_output", recorder)
    return recorder


def test_certified_sha_resolves_the_second_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_recorder(
        monkeypatch,
        ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"],
    )

    result = certified_sha("cccccccccccccccccccccccccccccccccccccccc")

    assert result == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert recorder.commands == ["git log -1 --format=%P cccccccccccccccccccccccccccccccccccccccc"]


def test_certified_sha_falls_back_to_self_on_non_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_recorder(monkeypatch, ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"])

    assert certified_sha("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_pull_digest_manifest_returns_none_when_no_registry() -> None:
    assert pull_digest_manifest(None, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "", "") is None


def test_pull_digest_manifest_returns_none_when_build_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builds, "build_exists", FixedReturn(False))

    assert pull_digest_manifest("ghcr.io/owner/repo/builds", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "", "") is None


def test_pull_digest_manifest_pulls_the_sha_tag_and_parses_entries(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(builds, "build_exists", build_exists_recorder)
    monkeypatch.setattr(builds, "pull_build", fake_pull_build)

    sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    result = pull_digest_manifest("ghcr.io/owner/repo/builds", sha, "", "")

    assert result is not None
    assert build_exists_recorder.calls[0][3] == f"sha-{sha}"
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
