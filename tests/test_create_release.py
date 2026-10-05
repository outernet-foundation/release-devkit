import pytest
import typer

from release_devkit.create_release import matched_ci_run_number


class SequentialOutputs:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        return self.outputs.pop(0)


def patch_recorder(monkeypatch: pytest.MonkeyPatch, outputs: list[str]) -> SequentialOutputs:
    recorder = SequentialOutputs(outputs)
    monkeypatch.setattr("release_devkit.create_release.bash_output", recorder)
    return recorder


def test_matched_ci_run_number_queries_resolved_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_recorder(monkeypatch, ["def456\n", "42\n"])

    result = matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")

    assert result == "42"
    assert ".parents[1].sha // .sha" in recorder.commands[0]
    assert "head_sha=def456" in recorder.commands[1]
    assert "workflows/integrate.yml/runs" in recorder.commands[1]


def test_matched_ci_run_number_falls_back_to_promoted_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = patch_recorder(monkeypatch, ["abc1234\n", "7\n"])

    result = matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")

    assert result == "7"
    assert "head_sha=abc1234" in recorder.commands[1]


def test_matched_ci_run_number_exits_when_no_run(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_recorder(monkeypatch, ["abc1234\n", "\n"])

    with pytest.raises(typer.Exit) as exit_info:
        matched_ci_run_number("owner/repo", "abc1234", "integrate.yml")
    assert exit_info.value.exit_code == 1
