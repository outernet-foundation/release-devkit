from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TypeGuard

import typer
import yaml
from bashrun.bash import CalledProcessError, bash, bash_output

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ACTIONLINT_VERSION = "1.7.12"
CHECKOUT_USES = "actions/checkout@v5"
DEVKIT_WRAPPER_USES = "./.github/actions/setup-release-devkit"
DEVKIT_WRAPPER_PATH = Path(".github/actions/setup-release-devkit/action.yml")
DEVKIT_REPOSITORY = "outernet-foundation/release-devkit"
DEVKIT_INSTALL_PATH = "$RUNNER_TEMP/release-devkit"
DEVKIT_INVOCATION_PREFIX = f'uv run --project "{DEVKIT_INSTALL_PATH}" --locked --no-dev '
SETUP_UV_USES = "astral-sh/setup-uv@v7"
SNAPSHOT_REF = "${{ github.head_ref || github.ref_name }}"
MERGE_BOT_REF = "${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}"
MERGE_GATE_JOB_IF = (
    "github.event.label.name == 'ready-to-merge'"
    " || (github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success')"
)
MERGE_GATE_CONCURRENCY = "merge-gate-${{ github.event.pull_request.number || github.event.workflow_run.head_branch }}"
MINT_STEP_USES = "actions/create-github-app-token@v3"
MINT_STEP_INPUTS = {
    "app-id": "${{ vars.MERGE_BOT_APP_ID }}",
    "private-key": "${{ secrets.MERGE_BOT_APP_PRIVATE_KEY }}",
}
DEFAULT_WORKFLOWS = [
    Path(".github/workflows/integrate.yml"),
    Path(".github/workflows/release.yml"),
    Path(".github/workflows/merge-gate.yml"),
]

DEAD_USES_PREFIXES = ("./.release-devkit/", "./.github/actions/checkout-release-devkit")

CONSUMER_LEDGER = "consumer-ledger"
CONSUMER_LEDGER_PUSH = "consumer-ledger-push"
SNAPSHOT = "snapshot"
MERGE_BOT = "merge-bot"

SIGNATURES: dict[str, dict[str, object]] = {
    CONSUMER_LEDGER: {"fetch-depth": 0, "fetch-tags": True, "persist-credentials": False},
    CONSUMER_LEDGER_PUSH: {"fetch-depth": 0, "fetch-tags": True},
    SNAPSHOT: {"ref": SNAPSHOT_REF, "persist-credentials": False},
    MERGE_BOT: {"ref": MERGE_BOT_REF, "fetch-depth": 0, "persist-credentials": False},
}

WRAPPER_CLONE = re.compile(
    r"^git clone https://github\.com/outernet-foundation/release-devkit\.git"
    r' "\$RUNNER_TEMP/release-devkit"'
    r' && git -C "\$RUNNER_TEMP/release-devkit" checkout [0-9a-f]{40}$'
)
DEVKIT_INVOCATION = re.compile(
    re.escape(DEVKIT_INVOCATION_PREFIX)
    + r"(?P<verb>get-app-version|release|publish-prerelease|ensure-release-pr|lint-workflows|merge-gate)"
    + r'(?P<args>(?: [^)"]*)?)'
)
VERB_ARGS: dict[str, re.Pattern[str]] = {
    "get-app-version": re.compile(r"^ --app \S+$"),
    "release": re.compile(r"^( --dry-run)?$"),
    "publish-prerelease": re.compile(r"^$"),
    "ensure-release-pr": re.compile(r"^$"),
    "lint-workflows": re.compile(r"^$"),
    "merge-gate": re.compile(r"^$"),
}
VERB_ENV: dict[str, dict[str, str]] = {
    "release": {"GITHUB_TOKEN": "${{ github.token }}"},
    "ensure-release-pr": {"GITHUB_TOKEN": "${{ github.token }}"},
    "merge-gate": {
        "GITHUB_TOKEN": "${{ steps.mint.outputs.token }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}",
    },
}

PLATFORMS = {
    ("Linux", "x86_64"): "linux_amd64",
    ("Linux", "aarch64"): "linux_arm64",
    ("Darwin", "x86_64"): "darwin_amd64",
    ("Darwin", "arm64"): "darwin_arm64",
}


@dataclass
class CheckoutStep:
    step_index: int
    signature: str


@dataclass
class VerbStep:
    step_index: int
    name: str
    dry_run: bool


@app.command()
def main(
    workflows: Annotated[
        list[Path] | None,
        typer.Option(
            "--workflow", help="Workflow file to signature-validate (repeatable; default integrate + publish)"
        ),
    ] = None,
) -> None:
    workflow_paths = workflows or DEFAULT_WORKFLOWS
    problems: list[str] = []
    for workflow_path in workflow_paths:
        problems.extend(validate_workflow_file(workflow_path))
    problems.extend(validate_devkit_wrapper())
    for problem in problems:
        print(problem)
    run_actionlint()
    if problems:
        raise SystemExit(1)


def is_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def is_string_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def validate_devkit_wrapper(path: Path = DEVKIT_WRAPPER_PATH) -> list[str]:
    if not path.is_file():
        return [f"{path}: wrapper action not found"]
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not is_mapping(document):
        return [f"{path}: wrapper is not a YAML mapping"]
    runs_value = document.get("runs")
    if not is_mapping(runs_value) or runs_value.get("using") != "composite":
        return [f"{path}: wrapper must be a composite action"]
    steps_value = runs_value.get("steps")
    steps = steps_value if is_object_list(steps_value) else []
    if len(steps) != 2 or not is_mapping(steps[0]) or not is_mapping(steps[1]):
        return [f"{path}: wrapper must contain exactly two steps (setup-uv, clone)"]
    problems: list[str] = []
    if steps[0].get("uses") != SETUP_UV_USES:
        problems.append(f"{path}: wrapper first step must be {SETUP_UV_USES}")
    with_value = steps[0].get("with")
    if not is_mapping(with_value) or with_value.get("enable-cache") is not True:
        problems.append(f"{path}: wrapper first step must set enable-cache: true")
    if steps[1].get("shell") != "bash":
        problems.append(f"{path}: wrapper second step must set shell: bash")
    run_value = steps[1].get("run")
    if not isinstance(run_value, str) or not WRAPPER_CLONE.fullmatch(run_value.strip()):
        problems.append(
            f"{path}: wrapper second step must clone {DEVKIT_REPOSITORY} into {DEVKIT_INSTALL_PATH}"
            " and checkout the pinned commit"
        )
    return problems


def validate_workflow_file(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path}: workflow file not found"]
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not is_mapping(document):
        return [f"{path}: workflow is not a YAML mapping"]
    jobs_value = document.get("jobs")
    if not is_mapping(jobs_value):
        return [f"{path}: no jobs mapping"]
    problems: list[str] = []
    for job_name, job_value in jobs_value.items():
        problems.extend(validate_job(str(job_name), job_value, path))
    if path.name == "merge-gate.yml":
        problems.extend(validate_merge_gate_triggers(document, path))
        problems.extend(validate_merge_gate_concurrency(document, path))
        for job_name, job_value in jobs_value.items():
            if is_mapping(job_value) and job_value.get("if") != MERGE_GATE_JOB_IF:
                problems.append(f"{path}: job '{job_name}': merge-gate.yml jobs must gate on if: {MERGE_GATE_JOB_IF}")
    return problems


def validate_merge_gate_triggers(document: dict[object, object], path: Path) -> list[str]:
    on_value = document.get("on")
    if not is_mapping(on_value):
        on_value = document.get(True)
    problems: list[str] = []
    if is_mapping(on_value):
        pull_request = on_value.get("pull_request")
        workflow_run = on_value.get("workflow_run")
    else:
        pull_request = None
        workflow_run = None
    if (
        not is_mapping(pull_request)
        or pull_request.get("types") != ["labeled"]
        or pull_request.get("branches") != ["dev"]
    ):
        problems.append(f"{path}: must trigger on pull_request to dev, types [labeled] only")
    if (
        not is_mapping(workflow_run)
        or workflow_run.get("workflows") != ["Integrate"]
        or workflow_run.get("types") != ["completed"]
    ):
        problems.append(f"{path}: must trigger on workflow_run from Integrate, types [completed] only")
    return problems


def validate_merge_gate_concurrency(document: dict[object, object], path: Path) -> list[str]:
    concurrency = document.get("concurrency")
    if not is_mapping(concurrency) or concurrency.get("group") != MERGE_GATE_CONCURRENCY:
        return [f"{path}: concurrency group must be {MERGE_GATE_CONCURRENCY} (the || fallback is load-bearing)"]
    if "cancel-in-progress" in concurrency:
        return [f"{path}: concurrency must omit cancel-in-progress — serialization is the policy"]
    return []


def validate_job(job_name: str, job_value: object, path: Path) -> list[str]:
    if not is_mapping(job_value):
        return [f"{path}: job '{job_name}' is not a mapping"]
    steps_value = job_value.get("steps")
    steps = steps_value if is_object_list(steps_value) else []
    checkout_steps, problems = collect_checkout_steps(job_name, steps, path)
    verb_steps, verb_problems = collect_verb_steps(job_name, steps, path)
    problems.extend(verb_problems)
    problems.extend(collect_dead_uses(job_name, steps, path))
    if not verb_steps:
        return problems
    is_merge_gate_job = any(verb.name == "merge-gate" for verb in verb_steps)
    is_real_publish = any(verb.name == "release" and not verb.dry_run for verb in verb_steps)
    if is_merge_gate_job:
        required_consumer = MERGE_BOT
    elif is_real_publish:
        required_consumer = CONSUMER_LEDGER_PUSH
    else:
        required_consumer = CONSUMER_LEDGER
    if required_consumer != CONSUMER_LEDGER_PUSH and any(
        step.signature == CONSUMER_LEDGER_PUSH for step in checkout_steps
    ):
        problems.append(
            f"{path}: job '{job_name}': consumer-ledger-push checkout is reserved for real release jobs"
        )
    if required_consumer != MERGE_BOT and any(step.signature == MERGE_BOT for step in checkout_steps):
        problems.append(f"{path}: job '{job_name}': merge-bot checkout is reserved for merge-gate jobs")
    first_verb_index = min(verb.step_index for verb in verb_steps)
    wrapper_indexes = [
        index
        for index, step_value in enumerate(steps)
        if is_mapping(step_value) and step_value.get("uses") == DEVKIT_WRAPPER_USES
    ]
    wrappers_before = [index for index in wrapper_indexes if index < first_verb_index]
    if not wrappers_before:
        problems.append(f"{path}: job '{job_name}': no {DEVKIT_WRAPPER_USES} step precedes the release-devkit verb")
        return problems
    earliest_wrapper_index = min(wrappers_before)
    has_consumer = any(
        step.signature == required_consumer and step.step_index < earliest_wrapper_index for step in checkout_steps
    )
    if not has_consumer:
        problems.append(
            f"{path}: job '{job_name}': no {required_consumer} checkout precedes the setup-release-devkit step"
        )
    mint_indexes: list[int] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value) or step_value.get("uses") != MINT_STEP_USES:
            continue
        with_value = step_value.get("with")
        if step_value.get("id") != "mint" or with_value != MINT_STEP_INPUTS:
            problems.append(
                f"{path}: job '{job_name}' step {index}: create-github-app-token must be the canonical mint step"
                " (id: mint, app-id from the MERGE_BOT_APP_ID var, private-key from the MERGE_BOT_APP_PRIVATE_KEY secret)"
            )
            continue
        mint_indexes.append(index)
    if is_merge_gate_job and not any(earliest_wrapper_index < index < first_verb_index for index in mint_indexes):
        problems.append(
            f"{path}: job '{job_name}': merge-gate requires a canonical {MINT_STEP_USES} mint step"
            " between the wrapper and the verb"
        )
    return problems


def collect_dead_uses(job_name: str, steps: list[object], path: Path) -> list[str]:
    problems: list[str] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value):
            continue
        uses_value = step_value.get("uses")
        if isinstance(uses_value, str) and uses_value.startswith(DEAD_USES_PREFIXES):
            problems.append(
                f"{path}: job '{job_name}' step {index}: {uses_value} is the dead composite-action model;"
                " verbs are plain run steps against $RUNNER_TEMP/release-devkit"
            )
    return problems


def collect_verb_steps(job_name: str, steps: list[object], path: Path) -> tuple[list[VerbStep], list[str]]:
    verb_steps: list[VerbStep] = []
    problems: list[str] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value):
            continue
        run_value = step_value.get("run")
        if not isinstance(run_value, str) or DEVKIT_INSTALL_PATH not in run_value:
            continue
        prefix_count = run_value.count(DEVKIT_INVOCATION_PREFIX)
        matches = list(DEVKIT_INVOCATION.finditer(run_value))
        if not prefix_count or len(matches) != prefix_count:
            problems.append(
                f"{path}: job '{job_name}' step {index}: mentions {DEVKIT_INSTALL_PATH}"
                f" without a canonical {DEVKIT_INVOCATION_PREFIX.strip()}<verb> invocation"
            )
            continue
        for match in matches:
            verb = match.group("verb")
            args = match.group("args")
            if not VERB_ARGS[verb].fullmatch(args):
                problems.append(
                    f"{path}: job '{job_name}' step {index}: {verb} carries rejected arguments ({args.strip()})"
                )
                continue
            problems.extend(validate_verb_env(job_name, index, verb, step_value, path))
            verb_steps.append(VerbStep(step_index=index, name=verb, dry_run=args == " --dry-run"))
    return verb_steps, problems


def validate_verb_env(
    job_name: str, step_index: int, verb: str, step_value: dict[object, object], path: Path
) -> list[str]:
    problems: list[str] = []
    env_value = step_value.get("env")
    env: dict[object, object] = env_value if is_mapping(env_value) else {}
    for key, value in VERB_ENV.get(verb, {}).items():
        if env.get(key) != value:
            problems.append(f"{path}: job '{job_name}' step {step_index}: {verb} requires env {key}: {value}")
    return problems


def collect_checkout_steps(job_name: str, steps: list[object], path: Path) -> tuple[list[CheckoutStep], list[str]]:
    checkout_steps: list[CheckoutStep] = []
    problems: list[str] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value):
            continue
        uses_value = step_value.get("uses")
        if not isinstance(uses_value, str):
            continue
        if uses_value.startswith("actions/checkout") and uses_value != CHECKOUT_USES:
            problems.append(
                f"{path}: job '{job_name}' step {index}: checkout must be {CHECKOUT_USES}, got {uses_value}"
            )
            continue
        if uses_value != CHECKOUT_USES:
            continue
        with_value = step_value.get("with")
        with_block: dict[str, object] = with_value if is_string_mapping(with_value) else {}
        signature = next((name for name, expected in SIGNATURES.items() if with_block == expected), None)
        if signature is None:
            rendered = json.dumps(with_block, sort_keys=True)
            problems.append(f"{path}: job '{job_name}' step {index}: checkout matches no signature; with={rendered}")
        else:
            checkout_steps.append(CheckoutStep(step_index=index, signature=signature))
    return checkout_steps, problems


def run_actionlint() -> None:
    workflows_directory = Path(".github/workflows")
    workflow_files = sorted(workflows_directory.glob("*.yml")) if workflows_directory.is_dir() else []
    if not workflow_files:
        raise SystemExit("no .github/workflows/*.yml files found")
    command = " ".join(str(part) for part in [ensure_actionlint(), *workflow_files])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def ensure_actionlint() -> Path:
    cache_directory = actionlint_cache_dir()
    binary = cache_directory / "actionlint"
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in PLATFORMS:
        raise SystemExit(f"no actionlint build for {platform.system()}/{platform.machine()}")
    build = PLATFORMS[platform_key]
    release_base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
    tarball_name = f"actionlint_{ACTIONLINT_VERSION}_{build}.tar.gz"
    tarball = cache_directory / tarball_name
    bash(f"curl -fsSL {release_base}/{tarball_name} -o {tarball}")
    checksums = bash_output(f"curl -fsSL {release_base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt")
    expected = expected_checksum(checksums, tarball_name)
    actual = bash_output(f"sha256sum {tarball}").split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(
            f"actionlint {ACTIONLINT_VERSION} checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
        )
    bash(f"tar -xzf {tarball} -C {cache_directory}")
    if not binary.is_file():
        raise SystemExit(f"actionlint binary missing after extracting {tarball_name}")
    return binary


def actionlint_cache_dir() -> Path:
    return Path.home() / ".cache" / "release-devkit" / f"actionlint-v{ACTIONLINT_VERSION}"


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")
