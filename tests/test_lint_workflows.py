import re
from pathlib import Path

import pytest

from release_devkit.verbs.lint_workflows import (
    ACTIONLINT_BUILDS,
    MERGE_GATE_WORKFLOW,
    Problem,
    RELEASE_WORKFLOW,
    ZIZMOR_BUILDS,
    found_action_files,
    found_workflows,
    render_problem,
    validate_action_file,
    validate_toolkit_pin_consistency,
    validate_workflow_file,
)

GOOD_SHA = "a" * 40
OTHER_SHA = "b" * 40
TOOLKIT = "outernet-foundation/github-actions-toolkit"


def test_audit_binaries_cover_the_same_platforms() -> None:
    assert set(ZIZMOR_BUILDS) == set(ACTIONLINT_BUILDS)


def test_zizmor_builds_carry_sha256_checksums() -> None:
    for tarball_name, checksum in ZIZMOR_BUILDS.values():
        assert tarball_name.startswith("zizmor-") and tarball_name.endswith(".tar.gz")
        assert re.fullmatch(r"[0-9a-f]{64}", checksum)


def messages_of(problems: list[Problem]) -> list[str]:
    return [render_problem(problem) for problem in problems]


def rendered(problems: list[Problem]) -> str:
    return " ".join(messages_of(problems))


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def workflow_with_uses(uses: str) -> str:
    return f"""
jobs:
  job:
    runs-on: ubuntu-latest
    steps:
      - uses: {uses}
"""


def test_toolkit_ref_with_full_sha_is_accepted(tmp_path: Path) -> None:
    path = write(tmp_path / "workflow.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/preflight.yml@{GOOD_SHA}"))
    pins: dict[Path, str] = {}
    assert messages_of(validate_workflow_file(path, pins)) == []
    assert pins == {path: GOOD_SHA}


def test_toolkit_ref_without_full_sha_is_flagged(tmp_path: Path) -> None:
    path = write(tmp_path / "workflow.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/preflight.yml@dev"))
    pins: dict[Path, str] = {}
    assert "must pin a full 40-hex commit SHA" in rendered(validate_workflow_file(path, pins))


def test_short_sha_is_flagged(tmp_path: Path) -> None:
    path = write(
        tmp_path / "workflow.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/preflight.yml@{GOOD_SHA[:12]}")
    )
    pins: dict[Path, str] = {}
    assert "must pin a full 40-hex commit SHA" in rendered(validate_workflow_file(path, pins))


def test_stale_repository_spelling_is_flagged(tmp_path: Path) -> None:
    path = write(
        tmp_path / "workflow.yml",
        workflow_with_uses(f"outernet-foundation/release-devkit/.github/workflows/preflight.yml@{GOOD_SHA}"),
    )
    pins: dict[Path, str] = {}
    assert "stale toolkit spelling" in rendered(validate_workflow_file(path, pins))


def test_non_toolkit_refs_are_not_pin_checked(tmp_path: Path) -> None:
    path = write(tmp_path / "workflow.yml", workflow_with_uses("actions/checkout@v5"))
    pins: dict[Path, str] = {}
    assert messages_of(validate_workflow_file(path, pins)) == []


def test_divergent_toolkit_pins_across_files_are_flagged(tmp_path: Path) -> None:
    first = write(tmp_path / "one.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/preflight.yml@{GOOD_SHA}"))
    second = write(tmp_path / "two.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/mirror.yml@{OTHER_SHA}"))
    pins: dict[Path, str] = {}
    validate_workflow_file(first, pins)
    validate_workflow_file(second, pins)
    assert "must carry the same SHA" in rendered(validate_toolkit_pin_consistency(pins))


def test_agreeing_toolkit_pins_pass(tmp_path: Path) -> None:
    first = write(tmp_path / "one.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/preflight.yml@{GOOD_SHA}"))
    second = write(tmp_path / "two.yml", workflow_with_uses(f"{TOOLKIT}/.github/workflows/mirror.yml@{GOOD_SHA}"))
    pins: dict[Path, str] = {}
    validate_workflow_file(first, pins)
    validate_workflow_file(second, pins)
    assert messages_of(validate_toolkit_pin_consistency(pins)) == []


def test_yaml_anchors_on_the_uses_scalar_resolve(tmp_path: Path) -> None:
    text = f"""
jobs:
  one:
    runs-on: ubuntu-latest
    steps:
      - uses: &toolkit {TOOLKIT}/.github/workflows/preflight.yml@{GOOD_SHA}
  two:
    runs-on: ubuntu-latest
    steps:
      - uses: *toolkit
"""
    path = write(tmp_path / "workflow.yml", text)
    pins: dict[Path, str] = {}
    assert messages_of(validate_workflow_file(path, pins)) == []
    assert pins == {path: GOOD_SHA}


def test_job_level_uses_refs_are_pin_checked(tmp_path: Path) -> None:
    text = f"""
jobs:
  preflight:
    uses: {TOOLKIT}/.github/workflows/preflight.yml@dev
"""
    path = write(tmp_path / "workflow.yml", text)
    pins: dict[Path, str] = {}
    assert "must pin a full 40-hex commit SHA" in rendered(validate_workflow_file(path, pins))


VALID_RELEASE = """
concurrency:
  group: release-${{ github.ref }}

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


def test_release_concurrency_shape_is_enforced(tmp_path: Path) -> None:
    valid = write(tmp_path / RELEASE_WORKFLOW, VALID_RELEASE)
    assert messages_of(validate_workflow_file(valid, {})) == []

    canceling = VALID_RELEASE.replace(
        "group: release-${{ github.ref }}", "group: release-${{ github.ref }}\n  cancel-in-progress: true"
    )
    cancel = write(tmp_path / RELEASE_WORKFLOW, canceling)
    assert "must omit cancel-in-progress" in rendered(validate_workflow_file(cancel, {}))

    wrong = write(tmp_path / RELEASE_WORKFLOW, VALID_RELEASE.replace("release-${{ github.ref }}", "other"))
    assert "concurrency group must be release-${{ github.ref }}" in rendered(validate_workflow_file(wrong, {}))


def test_release_contract_does_not_apply_to_other_filenames(tmp_path: Path) -> None:
    path = write(tmp_path / "nightly.yml", VALID_RELEASE.replace("release-${{ github.ref }}", "nightly"))
    assert messages_of(validate_workflow_file(path, {})) == []


VALID_MERGE_GATE = """
on:
  pull_request:
    branches: [dev]
    types: [labeled]

concurrency:
  group: merge-gate-${{ github.event.pull_request.number }}

jobs:
  merge-gate:
    uses: ./.github/workflows/merge-gate.yml
"""


def test_merge_gate_wake_shape_is_enforced(tmp_path: Path) -> None:
    valid = write(tmp_path / MERGE_GATE_WORKFLOW, VALID_MERGE_GATE)
    assert messages_of(validate_workflow_file(valid, {})) == []

    bad_types = VALID_MERGE_GATE.replace("types: [labeled]", "types: [opened, labeled]")
    opened = write(tmp_path / MERGE_GATE_WORKFLOW, bad_types)
    assert "types [labeled] only" in rendered(validate_workflow_file(opened, {}))

    workflow_run = VALID_MERGE_GATE.replace(
        "concurrency:", "  workflow_run:\n    workflows: [Integrate]\n\nconcurrency:"
    )
    runner = write(tmp_path / MERGE_GATE_WORKFLOW, workflow_run)
    assert "workflow_run is forbidden" in rendered(validate_workflow_file(runner, {}))

    canceling = VALID_MERGE_GATE.replace(
        "group: merge-gate-${{ github.event.pull_request.number }}",
        "group: merge-gate-${{ github.event.pull_request.number }}\n  cancel-in-progress: true",
    )
    cancel = write(tmp_path / MERGE_GATE_WORKFLOW, canceling)
    assert "must omit cancel-in-progress" in rendered(validate_workflow_file(cancel, {}))


def test_action_files_are_scanned_for_toolkit_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write(
        tmp_path / ".github/actions/release/action.yml",
        f"""
runs:
  using: composite
  steps:
    - uses: {TOOLKIT}/.github/actions/release@{GOOD_SHA}
""",
    )
    assert [path.name for path in found_action_files()] == ["action.yml"]
    pins: dict[Path, str] = {}
    problems = validate_action_file(found_action_files()[0], pins)
    assert messages_of(problems) == []
    assert pins == {Path(".github/actions/release/action.yml"): GOOD_SHA}


def test_found_scan_discovers_yml_and_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / ".github/workflows/one.yml", "jobs: {}")
    write(tmp_path / ".github/workflows/two.yaml", "jobs: {}")
    assert [path.name for path in found_workflows()] == ["one.yml", "two.yaml"]
