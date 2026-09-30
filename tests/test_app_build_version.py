import yaml
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
                "ci_workflow": "ci.yml",
            },
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def invoke(monkeypatch: pytest.MonkeyPatch, tag_output: str, arguments: list[str]) -> Result:
    monkeypatch.setattr("release_devkit.ledger.bash_output", CommandRecorder(output=tag_output))
    return CliRunner().invoke(app, arguments)


def test_stamps_next_version_plus_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch,
        "capture-tool-v0.2.7\n",
        ["--app", "capture-tool", "--config", str(config_path), "--run-number", "42"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.8+42"


def test_run_number_defaults_to_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "412")

    result = invoke(monkeypatch, "capture-tool-v0.2.7\n", ["--app", "capture-tool", "--config", str(config_path)])

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.8+412"


def test_no_tags_defaults_to_first_in_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(monkeypatch, "", ["--app", "capture-tool", "--config", str(config_path), "--run-number", "1"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.0+1"


def test_prerelease_tags_do_not_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch,
        "capture-tool-v0.2.8-preview\ncapture-tool-v0.2.7\n",
        ["--app", "capture-tool", "--config", str(config_path), "--run-number", "1"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "0.2.8+1"


def test_unknown_app_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = write_config(tmp_path)

    result = invoke(
        monkeypatch, "capture-tool-v0.2.7\n", ["--app", "Nope", "--config", str(config_path), "--run-number", "1"]
    )

    assert result.exit_code == 1
