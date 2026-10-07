from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner, Result

from release_devkit.verbs.get_app_version import app


class TagRecorder:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        return self.output


class GitHead:
    def __init__(self, head: str, count: int) -> None:
        self.head = head
        self.count = count
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        if command.startswith("git rev-parse HEAD"):
            return f"{self.head}\n"
        return f"{self.count}\n"


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "apps": {
                    "capture-tool": {
                        "path": "apps/CaptureTool",
                        "major_minor": "0.2",
                    }
                },
            },
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def invoke(
    monkeypatch: pytest.MonkeyPatch, tag_output: str, head: str, count: int, arguments: list[str]
) -> tuple[Result, GitHead]:
    monkeypatch.setattr("release_devkit.tags.bash_output", TagRecorder(output=tag_output))
    git_head = GitHead(head=head, count=count)
    monkeypatch.setattr("release_devkit.verbs.get_app_version.bash_output", git_head)
    return CliRunner().invoke(app, arguments), git_head


FULL_HEAD = "abcdef1234567890abcdef1234567890abcdef12"


def test_stamps_next_version_plus_short_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result, git_head = invoke(
        monkeypatch,
        "capture-tool-v0.2.7\n",
        FULL_HEAD,
        42,
        ["--app", "capture-tool", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert result.output.splitlines() == [f"version=0.2.8+{FULL_HEAD[:12]}", "version-code=42"]
    assert git_head.commands == ["git rev-parse HEAD", "git rev-list --count HEAD -- apps/CaptureTool"]


def test_outputs_write_to_github_output_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    output_file = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    result, _ = invoke(
        monkeypatch,
        "capture-tool-v0.2.7\n",
        FULL_HEAD,
        7,
        ["--app", "capture-tool", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert result.output == ""
    assert output_file.read_text(encoding="utf-8") == f"version=0.2.8+{FULL_HEAD[:12]}\nversion-code=7\n"


def test_no_tags_defaults_to_first_in_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result, _ = invoke(monkeypatch, "", FULL_HEAD, 1, ["--app", "capture-tool", "--config", str(config_path)])

    assert result.exit_code == 0
    assert result.output.splitlines() == [f"version=0.2.0+{FULL_HEAD[:12]}", "version-code=1"]


def test_prerelease_tags_do_not_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result, _ = invoke(
        monkeypatch,
        "capture-tool-v0.2.8-preview\ncapture-tool-v0.2.7\n",
        FULL_HEAD,
        1,
        ["--app", "capture-tool", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert result.output.splitlines() == [f"version=0.2.8+{FULL_HEAD[:12]}", "version-code=1"]


def test_unknown_app_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result, _ = invoke(
        monkeypatch, "capture-tool-v0.2.7\n", FULL_HEAD, 1, ["--app", "Nope", "--config", str(config_path)]
    )

    assert result.exit_code == 1
