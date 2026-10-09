import json
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter
from typer.testing import CliRunner, Result

from release_devkit.verbs import matrix
from release_devkit.verbs.matrix import app

CAPTURE_TOOL_APP: dict[str, object] = {
    "path": "apps/CaptureTool",
    "major_minor": "0.2",
    "builds": [{"project": "CaptureTool", "platform": "AndroidMobile", "file": "CaptureTool.apk"}],
}

ENVELOPE = TypeAdapter(dict[str, object])


class TagRecorder:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        for prefix, output in self.outputs.items():
            if f'"{prefix}*"' in command:
                return output
        return ""


def write_config(tmp_path: Path, apps: Mapping[str, object] | None = None) -> Path:
    document = {"apps": apps if apps is not None else {"capture-tool": CAPTURE_TOOL_APP}}
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text(yaml.safe_dump(document, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return config_path


def invoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdin: str,
    tags: dict[str, str] | None = None,
    config_path: Path | None = None,
) -> tuple[Result, str]:
    monkeypatch.setattr("release_devkit.plan.bash_output", TagRecorder(outputs=tags or {}))
    output_file = tmp_path / "github-output"
    output_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    if config_path is None:
        config_path = write_config(tmp_path)
    result = CliRunner().invoke(app, ["--config", str(config_path)], input=stdin)
    return result, output_file.read_text(encoding="utf-8")


def legs_from_value(value: str) -> list[dict[str, object]]:
    envelope = ENVELOPE.validate_python(json.loads(value))
    include = envelope["include"]
    assert isinstance(include, list)
    return matrix.LEGS.validate_python(include)


def legs_of(output_text: str) -> list[dict[str, object]]:
    key, _, value = output_text.partition("=")
    assert key == "matrix"
    return legs_from_value(value)


def single_leg(output_text: str) -> dict[str, object]:
    legs = legs_of(output_text)
    assert len(legs) == 1
    return legs[0]


def test_owned_leg_gets_base_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, output = invoke(
        monkeypatch,
        tmp_path,
        '[{"project": "CaptureTool", "platform": "AndroidMobile"}]',
        tags={"capture-tool-v": "capture-tool-v0.2.7\n"},
    )

    assert result.exit_code == 0
    assert single_leg(output) == {
        "project": "CaptureTool",
        "platform": "AndroidMobile",
        "version": "0.2.8",
    }


def test_no_tags_defaults_to_first_in_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, output = invoke(monkeypatch, tmp_path, '[{"project": "CaptureTool"}]', tags={})

    assert result.exit_code == 0
    assert single_leg(output)["version"] == "0.2.0"


def test_prerelease_tags_do_not_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, output = invoke(
        monkeypatch,
        tmp_path,
        '[{"project": "CaptureTool"}]',
        tags={"capture-tool-v": "capture-tool-v0.2.8-preview\ncapture-tool-v0.2.7\n"},
    )

    assert result.exit_code == 0
    assert single_leg(output)["version"] == "0.2.8"


def test_unowned_project_builds_unversioned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, output = invoke(monkeypatch, tmp_path, '[{"project": "Ghost", "editor-image": "unityci/editor:x"}]')

    assert result.exit_code == 0
    assert single_leg(output) == {"project": "Ghost", "editor-image": "unityci/editor:x"}


def test_docker_leg_without_project_passes_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty_config = tmp_path / "release-devkit.yaml"
    empty_config.write_text("", encoding="utf-8")

    result, output = invoke(
        monkeypatch, tmp_path, '[{"targets": "player", "variant": "common"}]', config_path=empty_config
    )

    assert result.exit_code == 0
    assert single_leg(output) == {"targets": "player", "variant": "common"}


def test_two_apps_stamp_their_own_versions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    apps = {
        "capture-tool": CAPTURE_TOOL_APP,
        "other-tool": {
            "path": "apps/Other",
            "major_minor": "0.1",
            "builds": [{"project": "Other", "platform": "StandaloneWindows", "file": "Other.exe"}],
        },
    }
    config_path = write_config(tmp_path, apps)

    result, output = invoke(
        monkeypatch,
        tmp_path,
        '[{"project": "CaptureTool"}, {"project": "Other"}]',
        tags={"capture-tool-v": "capture-tool-v0.2.7\n", "other-tool-v": "other-tool-v0.1.2\n"},
        config_path=config_path,
    )

    assert result.exit_code == 0
    legs = legs_of(output)
    assert [leg["version"] for leg in legs] == ["0.2.8", "0.1.3"]


def test_tag_math_runs_once_per_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tag_recorder = TagRecorder(outputs={"capture-tool-v": "capture-tool-v0.2.7\n"})
    monkeypatch.setattr("release_devkit.plan.bash_output", tag_recorder)
    output_file = tmp_path / "github-output"
    output_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    stdin = '[{"project": "CaptureTool", "platform": "AndroidMobile"}, {"project": "CaptureTool", "platform": "iOS"}]'

    result = CliRunner().invoke(app, ["--config", str(write_config(tmp_path))], input=stdin)

    assert result.exit_code == 0
    assert len(tag_recorder.commands) == 2
    legs = legs_of(output_file.read_text(encoding="utf-8"))
    assert [leg["version"] for leg in legs] == ["0.2.8", "0.2.8"]


def test_project_built_by_two_apps_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    apps = {
        "first-tool": {
            "path": "apps/First",
            "major_minor": "0.1",
            "builds": [{"project": "Shared", "platform": "AndroidMobile", "file": "First.apk"}],
        },
        "second-tool": {
            "path": "apps/Second",
            "major_minor": "0.1",
            "builds": [{"project": "Shared", "platform": "StandaloneWindows", "file": "Second.exe"}],
        },
    }
    config_path = write_config(tmp_path, apps)

    result, _ = invoke(monkeypatch, tmp_path, '[{"project": "Shared"}]', config_path=config_path)

    assert result.exit_code != 0


def test_non_string_project_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, _ = invoke(monkeypatch, tmp_path, '[{"project": 3}]')

    assert result.exit_code != 0


def test_empty_leg_list_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, _ = invoke(monkeypatch, tmp_path, "[]")

    assert result.exit_code != 0


def test_non_object_leg_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, _ = invoke(monkeypatch, tmp_path, '["app"]')

    assert result.exit_code != 0


def test_malformed_json_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, _ = invoke(monkeypatch, tmp_path, "{")

    assert result.exit_code != 0


def test_stdout_when_github_output_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr("release_devkit.plan.bash_output", TagRecorder(outputs={}))

    result = CliRunner().invoke(app, ["--config", str(write_config(tmp_path))], input='[{"targets": "player"}]')

    assert result.exit_code == 0
    key, _, value = result.stdout.partition("=")
    assert key == "matrix"
    assert legs_from_value(value) == [{"targets": "player"}]
