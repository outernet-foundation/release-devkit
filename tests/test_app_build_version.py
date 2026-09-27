import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from release_devkit.app_build_version import app


class CommandRecorder:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[str] = []

    def __call__(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        self.commands.append(command)
        return self.output


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "release-devkit.json"
    config_path.write_text(
        json.dumps({
            "apps": [
                {
                    "name": "CaptureTool",
                    "path": "apps/CaptureTool",
                    "major_minor": "1.0",
                    "tag_prefix": "capture-tool",
                    "display_name": "Capture Tool",
                }
            ],
            "ci_workflow": "ci.yml",
        }),
        encoding="utf-8",
    )
    return config_path


def invoke(monkeypatch: pytest.MonkeyPatch, tag_output: str, arguments: list[str]) -> Result:
    monkeypatch.setattr("release_devkit.ledger.bash_output", CommandRecorder(output=tag_output))
    return CliRunner().invoke(app, arguments)


def test_dev_spelling_off_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch,
        "capture-tool-v0.2.7\n",
        ["--app", "CaptureTool", "--config", str(config_path), "--run-number", "42"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.7-dev+42"


def test_release_spelling_on_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    result = invoke(
        monkeypatch,
        "capture-tool-v0.2.7\n",
        ["--app", "CaptureTool", "--config", str(config_path), "--run-number", "42"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.7+42"


def test_run_number_defaults_to_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "412")

    result = invoke(monkeypatch, "capture-tool-v0.2.7\n", ["--app", "CaptureTool", "--config", str(config_path)])

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.7-dev+412"


def test_no_tags_fall_back_to_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(monkeypatch, "", ["--app", "CaptureTool", "--config", str(config_path), "--run-number", "1"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.0.0-dev+1"


def test_prerelease_tags_do_not_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch,
        "capture-tool-v0.2.8-preview\ncapture-tool-v0.2.7\n",
        ["--app", "CaptureTool", "--config", str(config_path), "--run-number", "1"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.7-dev+1"


def test_unknown_app_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch, "capture-tool-v0.2.7\n", ["--app", "Nope", "--config", str(config_path), "--run-number", "1"]
    )

    assert result.exit_code == 1
