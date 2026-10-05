import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from release_devkit import merge_gate
from release_devkit.merge_gate import Settings

HEAD_SHA = "a" * 40
GREEN_ROLLUP = [{"name": "lint-workflows", "status": "COMPLETED", "conclusion": "SUCCESS"}]


class CommandResponses:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def __call__(self, command: str) -> str:
        return self.responses[command]


class BashLog:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def __call__(self, command: str) -> None:
        self.commands.append(command)


def pr_view_payload(labels: list[str], rollup: Sequence[Mapping[str, str | None]], state: str = "OPEN") -> str:
    return json.dumps({
        "state": state,
        "headRefOid": HEAD_SHA,
        "labels": [{"name": name} for name in labels],
        "statusCheckRollup": rollup,
    })


def gate_responses(payload: str) -> dict[str, str]:
    return {
        f"git branch -r --contains {HEAD_SHA}": "  origin/feature-x\n",
        "gh pr list --head feature-x --base dev --json number,headRefOid": json.dumps([
            {"number": 7, "headRefOid": HEAD_SHA}
        ]),
        "gh pr view 7 --json state,headRefOid,labels,statusCheckRollup": payload,
        "gh pr view 7 --json headRefName --jq .headRefName": "feature-x\n",
        "git rev-parse HEAD": f"{HEAD_SHA}\n",
    }


def accept_any_bash_check(command: str) -> bool:
    return True


def noop_delete_draft(tag: str, repo: str) -> None:
    pass


def null_ci_step(label: str) -> object:
    return nullcontext()


def exit_message(exit_request: SystemExit) -> str:
    return str(exit_request.code)


def run_gate(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, str],
    environment: dict[str, str] | None = None,
    bash_check_fn: Callable[[str], bool] | None = None,
    delete_draft_fn: Callable[[str, str], None] | None = None,
) -> tuple[SystemExit | None, BashLog]:
    monkeypatch.delenv("HEAD_SHA", raising=False)
    for key, value in (environment or {"HEAD_SHA": HEAD_SHA}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(merge_gate, "bash_output", CommandResponses(responses))
    bash_log = BashLog()
    monkeypatch.setattr(merge_gate, "bash", bash_log)
    monkeypatch.setattr(merge_gate, "bash_check", bash_check_fn or accept_any_bash_check)
    monkeypatch.setattr(merge_gate, "ci_step", null_ci_step)
    monkeypatch.setattr(merge_gate, "delete_draft_release", delete_draft_fn or noop_delete_draft)
    try:
        merge_gate.main()
    except SystemExit as exit_request:
        return exit_request, bash_log
    return None, bash_log


def test_settings_requires_head_sha_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEAD_SHA", raising=False)
    with pytest.raises(ValidationError):
        Settings.model_validate({})
    assert "pr_number" not in Settings.model_fields
    monkeypatch.setenv("HEAD_SHA", HEAD_SHA)
    assert Settings.model_validate({}).head_sha == HEAD_SHA


def test_gate_refuses_without_the_ready_to_merge_label(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = gate_responses(pr_view_payload([], GREEN_ROLLUP))
    exit_request, bash_log = run_gate(monkeypatch, responses)
    assert exit_request is not None
    assert "ready-to-merge" in exit_message(exit_request)
    assert not any("push" in command for command in bash_log.commands)


def test_gate_refuses_a_pr_that_is_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = pr_view_payload(["ready-to-merge"], GREEN_ROLLUP, state="CLOSED")
    exit_request, _ = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is not None
    assert "not OPEN" in exit_message(exit_request)


def test_gate_refuses_terminal_check_failures_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    rollup = [{"name": "lint-workflows", "status": "COMPLETED", "conclusion": "FAILURE"}]
    payload = pr_view_payload(["ready-to-merge"], rollup)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is not None
    message = exit_message(exit_request)
    assert "checks not green" in message
    assert "PR #7" in message
    assert HEAD_SHA[:12] in message
    assert not any("push" in command for command in bash_log.commands)


def test_gate_exits_cleanly_while_checks_are_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    rollup = [
        {"name": "lint-workflows", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "preflight", "status": "IN_PROGRESS"},
        {"name": "build", "status": "QUEUED"},
    ]
    payload = pr_view_payload(["ready-to-merge"], rollup)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is None
    assert not any("push" in command for command in bash_log.commands)


def test_gate_lands_a_labeled_green_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = pr_view_payload(["ready-to-merge"], GREEN_ROLLUP)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is None
    assert any("git merge --no-ff" in command for command in bash_log.commands)
    assert any("push origin HEAD:refs/heads/dev" in command for command in bash_log.commands)


def test_gate_treats_skipped_checks_as_green(monkeypatch: pytest.MonkeyPatch) -> None:
    rollup = [
        {"name": "lint-workflows", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "unity-matrix", "status": "COMPLETED", "conclusion": "SKIPPED"},
    ]
    payload = pr_view_payload(["ready-to-merge"], rollup)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is None
    assert any("push origin HEAD:refs/heads/dev" in command for command in bash_log.commands)


def test_gate_ignores_its_own_check_run(monkeypatch: pytest.MonkeyPatch) -> None:
    rollup = [
        {"name": "lint-workflows", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "merge-gate", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]
    payload = pr_view_payload(["ready-to-merge"], rollup)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is None
    assert any("push origin HEAD:refs/heads/dev" in command for command in bash_log.commands)


def test_gate_refuses_when_no_open_pr_matches_the_head(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = gate_responses(pr_view_payload(["ready-to-merge"], GREEN_ROLLUP))
    responses["gh pr list --head feature-x --base dev --json number,headRefOid"] = json.dumps([
        {"number": 7, "headRefOid": "b" * 40}
    ])
    exit_request, _ = run_gate(monkeypatch, responses)
    assert exit_request is not None
    assert "none" in exit_message(exit_request)


def test_gate_refuses_ambiguous_pr_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = gate_responses(pr_view_payload(["ready-to-merge"], GREEN_ROLLUP))
    responses[f"git branch -r --contains {HEAD_SHA}"] = "  origin/feature-x\n  origin/feature-y\n"
    responses["gh pr list --head feature-y --base dev --json number,headRefOid"] = json.dumps([
        {"number": 9, "headRefOid": HEAD_SHA}
    ])
    exit_request, _ = run_gate(monkeypatch, responses)
    assert exit_request is not None
    assert "7, 9" in exit_message(exit_request)


def reject_ls_remote(command: str) -> bool:
    return "ls-remote" not in command


def test_gate_deletes_merged_branch_after_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = pr_view_payload(["ready-to-merge"], GREEN_ROLLUP)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload))
    assert exit_request is None
    assert any("push origin --delete feature-x" in command for command in bash_log.commands)


def test_gate_skips_branch_deletion_when_head_is_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = gate_responses(pr_view_payload(["ready-to-merge"], GREEN_ROLLUP))
    responses["gh pr view 7 --json headRefName --jq .headRefName"] = "dev\n"
    exit_request, bash_log = run_gate(monkeypatch, responses)
    assert exit_request is None
    assert not any("--delete" in command for command in bash_log.commands)


def test_gate_skips_branch_deletion_when_head_is_main(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = gate_responses(pr_view_payload(["ready-to-merge"], GREEN_ROLLUP))
    responses["gh pr view 7 --json headRefName --jq .headRefName"] = "main\n"
    exit_request, bash_log = run_gate(monkeypatch, responses)
    assert exit_request is None
    assert not any("--delete" in command for command in bash_log.commands)


def test_gate_tolerates_already_deleted_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = pr_view_payload(["ready-to-merge"], GREEN_ROLLUP)
    exit_request, bash_log = run_gate(monkeypatch, gate_responses(payload), bash_check_fn=reject_ls_remote)
    assert exit_request is None
    assert not any("push origin --delete" in command for command in bash_log.commands)


def test_gate_deletes_pr_draft_after_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = pr_view_payload(["ready-to-merge"], GREEN_ROLLUP)
    deleted: list[tuple[str, str]] = []

    def record_draft_deletion(tag: str, repo: str) -> None:
        deleted.append((tag, repo))

    exit_request, _ = run_gate(
        monkeypatch,
        gate_responses(payload),
        environment={"HEAD_SHA": HEAD_SHA, "GITHUB_REPOSITORY": "owner/repo"},
        delete_draft_fn=record_draft_deletion,
    )

    assert exit_request is None
    assert deleted == [("pr-7", "owner/repo")]
