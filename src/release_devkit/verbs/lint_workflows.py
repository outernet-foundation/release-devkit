from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path

import typer
import yaml
from bashrun.bash import CalledProcessError, bash, bash_output
from pydantic import TypeAdapter, ValidationError

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ROOT_DOCUMENT = TypeAdapter(dict[object, object])
STR_MAPPING = TypeAdapter(dict[str, object])
OBJECT_LIST = TypeAdapter(list[object])

WORKFLOWS_DIRECTORY = Path(".github/workflows")
ACTIONS_DIRECTORY = Path(".github/actions")
ZIZMOR_CONFIG = Path(__file__).with_name("zizmor.yaml")
ACTIONLINT_VERSION = "1.7.12"
ACTIONLINT_BUILDS = {
    ("Linux", "x86_64"): "linux_amd64",
    ("Linux", "aarch64"): "linux_arm64",
    ("Darwin", "x86_64"): "darwin_amd64",
    ("Darwin", "arm64"): "darwin_arm64",
}
ZIZMOR_VERSION = "1.30.1"
# no upstream checksums file exists, so each build carries its own sha256 — changing the expected hash takes a repo commit
ZIZMOR_BUILDS = {
    ("Linux", "x86_64"): (
        "zizmor-x86_64-unknown-linux-gnu.tar.gz",
        "e65324f4430c2717591937edcec90ccbefaf14c174f8ec9415e03ca875b46e1a",
    ),
    ("Linux", "aarch64"): (
        "zizmor-aarch64-unknown-linux-gnu.tar.gz",
        "7ff1dce33bdd18fd2a4affe63bdd47efcccca97b2cec1c1863ec26e9e2647540",
    ),
    ("Darwin", "x86_64"): (
        "zizmor-x86_64-apple-darwin.tar.gz",
        "10e6b18b11ea07e515a16f0f0518c7b07527bc9977c1fd5698181ce7f3554202",
    ),
    ("Darwin", "arm64"): (
        "zizmor-aarch64-apple-darwin.tar.gz",
        "e28d22b087f9ebb8d99da6e740d348c930f559961c7c3f12badda54f882195a2",
    ),
}
TOOLKIT_REPOSITORY = "outernet-foundation/github-actions-toolkit"
STALE_TOOLKIT_SPELLING = "outernet-foundation/release-devkit"
TOOLKIT_USES = re.compile(rf"^{re.escape(TOOLKIT_REPOSITORY)}/\S+@(\S+)$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
RELEASE_CONCURRENCY = "release-${{ github.ref }}"
MERGE_GATE_WORKFLOW = Path(".github/workflows/merge-gate.yml")
MERGE_GATE_CONCURRENCY = "merge-gate-${{ github.event.pull_request.number }}"
# actionlint has not shipped job.workflow_repository/job.workflow_sha support (rhysd/actionlint#696,
# #707); dormant while those contexts live only inside the toolkit-checkout composite (actionlint
# never parses composites) and kept for any future raw spelling in a workflow file. The $/ ignores
# bridge rhysd/actionlint#732: composites and the own preflight call are referenced via $/ and the
# regexes anchor on that spelling so ./-ref and remote-format errors stay live. All four retire
# when the ACTIONLINT_VERSION pin moves past the fixes
ACTIONLINT_IGNORE_FLAGS = [
    "-ignore",
    r"property.*workflow_repository.*not.defined",
    "-ignore",
    r"property.*workflow_sha.*not.defined",
    "-ignore",
    r"specifying.action.*\\$/.*ref.is.missing",
    "-ignore",
    r"reusable.workflow.call.*\\$/",
]


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str


@dataclass(frozen=True)
class WorkflowView:
    triggers: dict[str, object] | None
    concurrency: dict[str, object] | None
    uses_values: list[str]


@app.command()
def main() -> None:
    problems: list[Problem] = []
    toolkit_pins: dict[Path, str] = {}
    for workflow_path in found_workflows():
        problems.extend(validate_workflow_file(workflow_path, toolkit_pins))
    for action_path in found_action_files():
        problems.extend(validate_action_file(action_path, toolkit_pins))
    problems.extend(validate_toolkit_pin_consistency(toolkit_pins))
    for problem in problems:
        print(render_problem(problem))
    run_actionlint()
    run_zizmor()
    if problems:
        raise SystemExit(1)


def found_workflows() -> list[Path]:
    if not WORKFLOWS_DIRECTORY.is_dir():
        return []
    return sorted({*WORKFLOWS_DIRECTORY.glob("*.yml"), *WORKFLOWS_DIRECTORY.glob("*.yaml")})


def found_action_files() -> list[Path]:
    if not ACTIONS_DIRECTORY.is_dir():
        return []
    return sorted(ACTIONS_DIRECTORY.glob("**/action.yml"))


def validate_workflow_file(path: Path, toolkit_pins: dict[Path, str]) -> list[Problem]:
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    workflow, problems = parse_workflow(path, document)
    if workflow is None:
        return problems
    problems.extend(collect_pin_problems(path, workflow.uses_values, toolkit_pins))
    if path.name == RELEASE_WORKFLOW.name:
        problems.extend(validate_release_concurrency(workflow, path))
    if path.name == MERGE_GATE_WORKFLOW.name:
        problems.extend(validate_merge_gate_wake(workflow, path))
    return problems


def validate_action_file(path: Path, toolkit_pins: dict[Path, str]) -> list[Problem]:
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = parse_root_mapping(document)
    if root is None:
        return [file_problem(path, "action file is not a YAML mapping")]
    runs_value = parse_str_mapping(root.get("runs"))
    entries = parse_object_list(runs_value.get("steps")) if runs_value is not None else None
    uses_values: list[str] = []
    for step in entries or []:
        step_mapping = parse_str_mapping(step)
        if step_mapping is None:
            continue
        step_uses = step_mapping.get("uses")
        if isinstance(step_uses, str):
            uses_values.append(step_uses)
    return collect_pin_problems(path, uses_values, toolkit_pins)


def collect_pin_problems(path: Path, uses_values: list[str], toolkit_pins: dict[Path, str]) -> list[Problem]:
    problems: list[Problem] = []
    for uses in uses_values:
        if uses.startswith(STALE_TOOLKIT_SPELLING):
            problems.append(
                file_problem(
                    path,
                    f"stale toolkit spelling '{uses}' — the rename redirect must never mask"
                    f" the canonical '{TOOLKIT_REPOSITORY}'",
                )
            )
            continue
        match = TOOLKIT_USES.fullmatch(uses)
        if match is None:
            continue
        pin = match.group(1)
        if FULL_SHA.fullmatch(pin) is None:
            problems.append(file_problem(path, f"toolkit ref '{uses}' must pin a full 40-hex commit SHA"))
            continue
        toolkit_pins[path] = pin
    return problems


def validate_toolkit_pin_consistency(toolkit_pins: dict[Path, str]) -> list[Problem]:
    distinct = sorted(set(toolkit_pins.values()))
    if len(distinct) > 1:
        spelled = ", ".join(f"{pin} ({path})" for path, pin in toolkit_pins.items())
        return [
            Problem(
                path=Path("."),
                message=f"every toolkit ref in the repo must carry the same SHA, found {spelled}",
            )
        ]
    return []


def validate_release_concurrency(workflow: WorkflowView, path: Path) -> list[Problem]:
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != RELEASE_CONCURRENCY:
        return [file_problem(path, f"concurrency group must be {RELEASE_CONCURRENCY} (the per-ref delivery mutex)")]
    if "cancel-in-progress" in concurrency:
        return [
            file_problem(
                path,
                "concurrency must omit cancel-in-progress — a cancelled delivery run loses its"
                " dev-builds section permanently",
            )
        ]
    return []


def validate_merge_gate_wake(workflow: WorkflowView, path: Path) -> list[Problem]:
    triggers = workflow.triggers
    pull_request = parse_str_mapping(triggers.get("pull_request")) if triggers is not None else None
    problems: list[Problem] = []
    if pull_request is None or pull_request.get("types") != ["labeled"] or pull_request.get("branches") != ["dev"]:
        problems.append(file_problem(path, "must trigger on pull_request to dev, types [labeled] only"))
    if triggers is not None and "workflow_run" in triggers:
        problems.append(file_problem(path, "workflow_run is forbidden — the labeled wake is the sole trigger"))
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != MERGE_GATE_CONCURRENCY:
        problems.append(
            file_problem(path, f"concurrency group must be {MERGE_GATE_CONCURRENCY} (the per-PR lander queue)")
        )
    elif "cancel-in-progress" in concurrency:
        problems.append(file_problem(path, "concurrency must omit cancel-in-progress — serialization is the policy"))
    return problems


def parse_workflow(path: Path, document: object) -> tuple[WorkflowView | None, list[Problem]]:
    root = parse_root_mapping(document)
    if root is None:
        return None, [file_problem(path, "workflow is not a YAML mapping")]
    jobs_value = parse_str_mapping(root.get("jobs"))
    if jobs_value is None:
        return None, [file_problem(path, "no jobs mapping")]
    problems: list[Problem] = []
    uses_values: list[str] = []
    for job_name, job_value in jobs_value.items():
        job_mapping = parse_str_mapping(job_value)
        if job_mapping is None:
            problems.append(file_problem(path, f"job '{job_name}' is not a mapping"))
            continue
        job_uses = job_mapping.get("uses")
        if isinstance(job_uses, str):
            uses_values.append(job_uses)
        for step in parse_object_list(job_mapping.get("steps")) or []:
            step_mapping = parse_str_mapping(step)
            if step_mapping is None:
                continue
            step_uses = step_mapping.get("uses")
            if isinstance(step_uses, str):
                uses_values.append(step_uses)
    # yaml 1.1 parses a bare `on:` key as boolean True, so the trigger mapping hides under the True key
    triggers = parse_str_mapping(root.get("on"))
    if triggers is None:
        triggers = parse_str_mapping(root.get(True))
    return (
        WorkflowView(
            triggers=triggers,
            concurrency=parse_str_mapping(root.get("concurrency")),
            uses_values=uses_values,
        ),
        problems,
    )


def run_actionlint() -> None:
    workflow_files = found_workflows()
    if not workflow_files:
        raise SystemExit("no workflow files found in .github/workflows")
    binary = ensure_actionlint()
    command = " ".join([
        f'"{binary}"',
        *ACTIONLINT_IGNORE_FLAGS,
        *[f'"{workflow_file}"' for workflow_file in workflow_files],
    ])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def run_zizmor() -> None:
    # offline is the standing persona: no audit needs GH_TOKEN, so the lint job needs no new credentials
    # repo root, not .github/workflows: the composite actions under .github/actions must be audited too
    binary = ensure_zizmor()
    command = " ".join([
        f'"{binary}"',
        "--offline",
        "--format",
        "plain",
        "--no-progress",
        "--config",
        f'"{ZIZMOR_CONFIG}"',
        '"."',
    ])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def ensure_actionlint() -> Path:
    platform_key = (platform.system(), platform.machine())
    if platform_key not in ACTIONLINT_BUILDS:
        raise SystemExit(f"no actionlint build for {platform.system()}/{platform.machine()}")
    release_base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
    tarball_name = f"actionlint_{ACTIONLINT_VERSION}_{ACTIONLINT_BUILDS[platform_key]}.tar.gz"
    checksums = bash_output(f"curl -fsSL {release_base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt")
    return ensure_pinned_binary(
        "actionlint",
        ACTIONLINT_VERSION,
        tarball_name,
        expected_checksum(checksums, tarball_name),
        release_base,
    )


def ensure_zizmor() -> Path:
    platform_key = (platform.system(), platform.machine())
    if platform_key not in ZIZMOR_BUILDS:
        raise SystemExit(f"no zizmor build for {platform.system()}/{platform.machine()}")
    tarball_name, expected = ZIZMOR_BUILDS[platform_key]
    release_base = f"https://github.com/zizmorcore/zizmor/releases/download/v{ZIZMOR_VERSION}"
    return ensure_pinned_binary("zizmor", ZIZMOR_VERSION, tarball_name, expected, release_base)


def ensure_pinned_binary(name: str, version: str, tarball_name: str, expected: str, release_base: str) -> Path:
    cache_directory = Path.home() / ".cache" / "github-actions-toolkit" / f"{name}-v{version}"
    binary = cache_directory / name
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    tarball = cache_directory / tarball_name
    bash(f'curl -fsSL {release_base}/{tarball_name} -o "{tarball}"')
    actual = bash_output(f'sha256sum "{tarball}"').split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(f"{name} {version} checksum mismatch for {tarball_name}: expected {expected}, got {actual}")
    bash(f'tar -xzf "{tarball}" -C "{cache_directory}"')
    tarball.unlink()
    if not binary.is_file():
        raise SystemExit(f"{name} binary missing after extracting {tarball_name}")
    return binary


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")


def parse_root_mapping(value: object) -> dict[object, object] | None:
    try:
        return ROOT_DOCUMENT.validate_python(value)
    except ValidationError:
        return None


def parse_str_mapping(value: object) -> dict[str, object] | None:
    try:
        return STR_MAPPING.validate_python(value)
    except ValidationError:
        return None


def parse_object_list(value: object) -> list[object] | None:
    try:
        return OBJECT_LIST.validate_python(value)
    except ValidationError:
        return None


def file_problem(path: Path, message: str) -> Problem:
    return Problem(path=path, message=message)


def render_problem(problem: Problem) -> str:
    return f"{problem.path}: {problem.message}"
