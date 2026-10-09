from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from bashrun.bash import CalledProcessError, bash, bash_output
from pydantic import TypeAdapter, ValidationError

from release_devkit.config import load_config

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ROOT_DOCUMENT = TypeAdapter(dict[object, object])
STR_MAPPING = TypeAdapter(dict[str, object])
OBJECT_LIST = TypeAdapter(list[object])

WORKFLOWS_DIRECTORY = Path(".github/workflows")
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
CHECKOUT_USES = "./.github/actions/checkout"
DEVKIT_WRAPPER_USES = "./.github/actions/setup-release-devkit"
DEVKIT_WRAPPER_PATH = Path(".github/actions/setup-release-devkit/action.yml")
DEVKIT_REPOSITORY = "outernet-foundation/release-devkit"
DEVKIT_INSTALL_PATH = "$RUNNER_TEMP/release-devkit"
DEVKIT_INVOCATION_PREFIX = f'uv run --project "{DEVKIT_INSTALL_PATH}" --locked --no-dev '
DEVKIT_CLONE_PREFIX = f'git clone https://github.com/{DEVKIT_REPOSITORY}.git "{DEVKIT_INSTALL_PATH}"'
SETUP_UV_USES = "./.github/actions/setup-uv"
CONFIG_PATH = Path("release-devkit.yaml")
PR_HEAD_SHA = "${{ github.event.pull_request.head.sha }}"
PR_DRAFT_JOB_IF = "github.event.pull_request"
MERGE_GATE_JOB_IF = "github.event.label.name == 'ready-to-merge'"
MERGE_GATE_CONCURRENCY = "merge-gate-${{ github.event.pull_request.number }}"
MINT_TOKEN_ENV = {"GITHUB_TOKEN": "${{ steps.mint.outputs.token }}"}
GITHUB_TOKEN_ENV = {"GITHUB_TOKEN": "${{ github.token }}"}
NUGET_API_KEY_ENV = "NUGET_API_KEY"
NUGET_API_KEY_SOURCE = "${{ steps.nuget-login.outputs.NUGET_API_KEY }}"
INTEGRATE_WORKFLOW = Path(".github/workflows/integrate.yml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
RELEASE_CONCURRENCY = "release-${{ github.ref }}"
RELEASE_PUSH_BRANCHES = ["main", "dev"]
MERGE_GATE_WORKFLOW = Path(".github/workflows/merge-gate.yml")
LINT_WORKFLOWS_JOB = "lint-workflows"
VALIDATE_RELEASE_PLAN_JOB = "validate-release-plan"
PREFLIGHT_JOB = "preflight"
MIRROR_IMAGES_JOB = "mirror-images"
UPDATE_PR_DRAFT_JOB = "update-pr-draft-release"
PRERELEASE_JOB = "prerelease"
RELEASE_JOB = "release"
RELEASE_VERB = "release"
PR_CHANNEL = "pr"
DEV_CHANNEL = "dev"
STABLE_CHANNEL = "stable"
DRY_RUN_SUFFIX = " --dry-run"

# ref law: canonical filename -> required checkout ref (None = the file's checkouts must carry no ref)
REF_LAWS: dict[str, str | None] = {
    INTEGRATE_WORKFLOW.name: PR_HEAD_SHA,
    RELEASE_WORKFLOW.name: None,
    MERGE_GATE_WORKFLOW.name: PR_HEAD_SHA,
}

WRAPPER_COMMIT_ENV_VAR = "RELEASE_DEVKIT_COMMIT"
WRAPPER_COMMIT_ENV = re.compile(r"^[0-9a-f]{40}$")
WRAPPER_CLONE = re.compile(
    r"^git clone https://github\.com/outernet-foundation/release-devkit\.git"
    r' "\$RUNNER_TEMP/release-devkit"'
    rf'\ngit -C "\$RUNNER_TEMP/release-devkit" checkout "\${WRAPPER_COMMIT_ENV_VAR}"$'
)

ENV_STEP_REFERENCE = re.compile(r"\$\{\{ steps\.([A-Za-z0-9_-]+)\.outputs\.")


@dataclass(frozen=True)
class VerbSpec:
    name: str
    args: re.Pattern[str]
    env: dict[str, str]
    dry_run_env: dict[str, str] | None
    needs_tag_fetch: bool
    needs_history: bool
    delivery: bool


@dataclass(frozen=True)
class ChannelSpec:
    args: re.Pattern[str]
    env: dict[str, str]
    workflow: Path
    job: str
    delivery: bool


VERB_SPECS: dict[str, VerbSpec] = {
    "get-app-version": VerbSpec(
        name="get-app-version",
        args=re.compile(r"^ --app \S+$"),
        env={},
        dry_run_env=None,
        needs_tag_fetch=True,
        needs_history=False,
        delivery=False,
    ),
    "lint-workflows": VerbSpec(
        name="lint-workflows",
        args=re.compile(r"^$"),
        env={},
        dry_run_env=None,
        needs_tag_fetch=False,
        needs_history=False,
        delivery=False,
    ),
    "merge-gate": VerbSpec(
        name="merge-gate",
        args=re.compile(r"^ --head-sha .+$"),
        env=MINT_TOKEN_ENV,
        dry_run_env=GITHUB_TOKEN_ENV,
        needs_tag_fetch=False,
        needs_history=True,
        delivery=False,
    ),
    "validate-release-plan": VerbSpec(
        name="validate-release-plan",
        args=re.compile(r"^$"),
        env={},
        dry_run_env=None,
        needs_tag_fetch=True,
        needs_history=False,
        delivery=False,
    ),
}

RELEASE_CHANNELS: dict[str, ChannelSpec] = {
    PR_CHANNEL: ChannelSpec(
        args=re.compile(r"^ --channel pr$"),
        env=GITHUB_TOKEN_ENV,
        workflow=INTEGRATE_WORKFLOW,
        job=UPDATE_PR_DRAFT_JOB,
        delivery=False,
    ),
    DEV_CHANNEL: ChannelSpec(
        args=re.compile(r"^ --channel dev$"),
        env=GITHUB_TOKEN_ENV,
        workflow=RELEASE_WORKFLOW,
        job=PRERELEASE_JOB,
        delivery=True,
    ),
    STABLE_CHANNEL: ChannelSpec(
        args=re.compile(r"^ --channel stable$"),
        env=GITHUB_TOKEN_ENV,
        workflow=RELEASE_WORKFLOW,
        job=RELEASE_JOB,
        delivery=True,
    ),
}

# local-run flags the CI grammar deliberately does not enforce
UNENFORCED_FLAGS: dict[str, frozenset[str]] = {
    "get-app-version": frozenset({"--config"}),
    "lint-workflows": frozenset({"--workflow"}),
    "release": frozenset({"--config"}),
    "validate-release-plan": frozenset({"--config"}),
}

# the invocation grammar derives from the spec tables, so the regex can never drift from the verbs it validates
DEVKIT_INVOCATION = re.compile(
    re.escape(DEVKIT_INVOCATION_PREFIX)
    + r"(?P<verb>"
    + "|".join(sorted([*VERB_SPECS, RELEASE_VERB]))
    + r")"
    + r'(?P<args>(?: [^)"]*)?)'
)

SHELL_STATEMENT_SPLIT = re.compile(r"\n|&&|;")


@dataclass
class StepView:
    index: int
    uses: str | None
    run: str | None
    step_id: str | None
    with_block: dict[str, object] | None
    env: dict[str, object] | None


@dataclass
class JobView:
    steps: list[StepView]
    needs: list[str]
    if_condition: object
    has_environment: bool


@dataclass
class WorkflowView:
    name: str | None
    triggers: dict[str, object] | None
    concurrency: dict[str, object] | None
    jobs: dict[str, JobView]


@dataclass
class CheckoutStep:
    step_index: int
    with_block: dict[str, object]


@dataclass
class VerbStep:
    step_index: int
    name: str
    args: str
    channel: str | None
    spec: VerbSpec | ChannelSpec


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str
    job: str | None = None
    step_index: int | None = None


@app.command()
def main(
    workflows: Annotated[
        list[Path] | None,
        typer.Option(
            "--workflow",
            help="Workflow file to signature-validate (repeatable; default: every file found in .github/workflows)",
        ),
    ] = None,
) -> None:
    workflow_paths = workflows or found_workflows()
    problems: list[str] = []
    for workflow_path in workflow_paths:
        problems.extend(validate_workflow_file(workflow_path, nuget=declares_nuget()))
    problems.extend(validate_devkit_wrapper())
    for problem in problems:
        print(problem)
    run_actionlint()
    run_zizmor()
    if problems:
        raise SystemExit(1)


def found_workflows() -> list[Path]:
    if not WORKFLOWS_DIRECTORY.is_dir():
        return []
    return sorted({*WORKFLOWS_DIRECTORY.glob("*.yml"), *WORKFLOWS_DIRECTORY.glob("*.yaml")})


def declares_nuget() -> bool:
    if not CONFIG_PATH.is_file():
        return False
    config = load_config(CONFIG_PATH)
    return any(package.registry == "nuget" for package in config.packages.values())


def run_actionlint() -> None:
    workflow_files = found_workflows()
    if not workflow_files:
        raise SystemExit("no .github/workflows/*.yml files found")
    binary = ensure_actionlint()
    command = " ".join([f'"{binary}"', *[f'"{workflow_file}"' for workflow_file in workflow_files]])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def run_zizmor() -> None:
    # offline is the standing persona: no audit needs GH_TOKEN, so the lint job needs no new credentials
    # repo root, not .github/workflows: the composite wrappers under .github/actions must be audited too
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
    cache_directory = Path.home() / ".cache" / "release-devkit" / f"actionlint-v{ACTIONLINT_VERSION}"
    binary = cache_directory / "actionlint"
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in ACTIONLINT_BUILDS:
        raise SystemExit(f"no actionlint build for {platform.system()}/{platform.machine()}")
    build = ACTIONLINT_BUILDS[platform_key]
    release_base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
    tarball_name = f"actionlint_{ACTIONLINT_VERSION}_{build}.tar.gz"
    tarball = cache_directory / tarball_name
    bash(f'curl -fsSL {release_base}/{tarball_name} -o "{tarball}"')
    checksums = bash_output(f"curl -fsSL {release_base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt")
    expected = expected_checksum(checksums, tarball_name)
    actual = bash_output(f'sha256sum "{tarball}"').split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(
            f"actionlint {ACTIONLINT_VERSION} checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
        )
    bash(f'tar -xzf "{tarball}" -C "{cache_directory}"')
    tarball.unlink()
    if not binary.is_file():
        raise SystemExit(f"actionlint binary missing after extracting {tarball_name}")
    return binary


def ensure_zizmor() -> Path:
    cache_directory = Path.home() / ".cache" / "release-devkit" / f"zizmor-v{ZIZMOR_VERSION}"
    binary = cache_directory / "zizmor"
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in ZIZMOR_BUILDS:
        raise SystemExit(f"no zizmor build for {platform.system()}/{platform.machine()}")
    tarball_name, expected = ZIZMOR_BUILDS[platform_key]
    release_base = f"https://github.com/zizmorcore/zizmor/releases/download/v{ZIZMOR_VERSION}"
    tarball = cache_directory / tarball_name
    bash(f'curl -fsSL {release_base}/{tarball_name} -o "{tarball}"')
    actual = bash_output(f'sha256sum "{tarball}"').split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(
            f"zizmor {ZIZMOR_VERSION} checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
        )
    bash(f'tar -xzf "{tarball}" -C "{cache_directory}"')
    tarball.unlink()
    if not binary.is_file():
        raise SystemExit(f"zizmor binary missing after extracting {tarball_name}")
    return binary


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")


def validate_devkit_wrapper(path: Path = DEVKIT_WRAPPER_PATH) -> list[str]:
    if not path.is_file():
        return []
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = parse_root_mapping(document)
    if root is None:
        return rendered([file_problem(path, "wrapper is not a YAML mapping")])
    runs_value = parse_str_mapping(root.get("runs"))
    if runs_value is None or runs_value.get("using") != "composite":
        return rendered([file_problem(path, "wrapper must be a composite action")])
    entries = parse_object_list(runs_value.get("steps"))
    steps = entries if entries is not None else []
    if len(steps) != 1:
        return rendered([file_problem(path, "wrapper must contain exactly one step (the clone)")])
    step = parse_str_mapping(steps[0])
    if step is None:
        return rendered([file_problem(path, "wrapper must contain exactly one step (the clone)")])
    problems: list[Problem] = []
    if step.get("shell") != "bash":
        problems.append(file_problem(path, "wrapper step must set shell: bash"))
    env_value = parse_str_mapping(step.get("env"))
    if (
        env_value is None
        or list(env_value) != [WRAPPER_COMMIT_ENV_VAR]
        or not WRAPPER_COMMIT_ENV.fullmatch(str(env_value[WRAPPER_COMMIT_ENV_VAR]))
    ):
        problems.append(
            file_problem(path, f"wrapper step must carry the pinned commit in env {WRAPPER_COMMIT_ENV_VAR}")
        )
    run_value = step.get("run")
    if not isinstance(run_value, str) or not WRAPPER_CLONE.fullmatch(run_value.strip()):
        problems.append(
            file_problem(
                path,
                f"wrapper step must clone {DEVKIT_REPOSITORY} into {DEVKIT_INSTALL_PATH}"
                " and checkout the pinned commit",
            )
        )
    return rendered(problems)


def validate_workflow_file(path: Path, nuget: bool = False) -> list[str]:
    if not path.is_file():
        return rendered([file_problem(path, "workflow file not found")])
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    workflow, problems = parse_workflow(path, document)
    if workflow is None:
        return rendered(problems)
    verbs_by_job: dict[str, list[VerbStep]] = {}
    for job_name, job in workflow.jobs.items():
        job_problems, verb_steps = validate_job(job_name, job, path, nuget)
        problems.extend(job_problems)
        verbs_by_job[job_name] = verb_steps
    saver_steps = [
        (job_name, step.index)
        for job_name, job in workflow.jobs.items()
        for step in job.steps
        if is_cache_writing_setup_uv(step)
    ]
    if len(saver_steps) > 1:
        problems.append(
            file_problem(
                path,
                f"at most one cache-writing {SETUP_UV_USES} step per file, found {len(saver_steps)} at {saver_steps}",
            )
        )
    # contract checks dispatch on the canonical filenames; a found file under any other name gets signature checks only
    if path.name == INTEGRATE_WORKFLOW.name:
        problems.extend(validate_integrate_contract(workflow, verbs_by_job, path))
    if path.name == RELEASE_WORKFLOW.name:
        problems.extend(validate_release_contract(workflow, verbs_by_job, path))
    if path.name == MERGE_GATE_WORKFLOW.name:
        problems.extend(validate_merge_gate_triggers(workflow, path))
        problems.extend(validate_merge_gate_concurrency(workflow, path))
        for job_name, job in workflow.jobs.items():
            if job.if_condition != MERGE_GATE_JOB_IF:
                problems.append(
                    job_problem(path, job_name, f"merge-gate.yml jobs must gate on if: {MERGE_GATE_JOB_IF}")
                )
    return rendered(problems)


def parse_workflow(path: Path, document: object) -> tuple[WorkflowView | None, list[Problem]]:
    root = parse_root_mapping(document)
    if root is None:
        return None, [file_problem(path, "workflow is not a YAML mapping")]
    jobs_value = parse_str_mapping(root.get("jobs"))
    if jobs_value is None:
        return None, [file_problem(path, "no jobs mapping")]
    problems: list[Problem] = []
    jobs: dict[str, JobView] = {}
    for job_name, job_value in jobs_value.items():
        job_mapping = parse_str_mapping(job_value)
        if job_mapping is None:
            problems.append(job_problem(path, job_name, "is not a mapping"))
            continue
        steps, step_problems = parse_steps(path, job_name, job_mapping.get("steps"))
        problems.extend(step_problems)
        jobs[job_name] = JobView(
            steps=steps,
            needs=parse_needs(job_mapping.get("needs")),
            if_condition=job_mapping.get("if"),
            has_environment="environment" in job_mapping,
        )
    # yaml 1.1 parses a bare `on:` key as boolean True, so the trigger mapping hides under the True key
    triggers = parse_str_mapping(root.get("on"))
    if triggers is None:
        triggers = parse_str_mapping(root.get(True))
    name_value = root.get("name")
    workflow = WorkflowView(
        name=name_value if isinstance(name_value, str) else None,
        triggers=triggers,
        concurrency=parse_str_mapping(root.get("concurrency")),
        jobs=jobs,
    )
    return workflow, problems


def parse_steps(path: Path, job_name: str, steps_value: object) -> tuple[list[StepView], list[Problem]]:
    entries = parse_object_list(steps_value)
    if entries is None:
        return [], []
    steps: list[StepView] = []
    problems: list[Problem] = []
    for index, step_value in enumerate(entries):
        step_mapping = parse_str_mapping(step_value)
        if step_mapping is None:
            problems.append(step_problem(path, job_name, index, "step is not a mapping"))
            continue
        uses_value = step_mapping.get("uses")
        run_value = step_mapping.get("run")
        step_id_value = step_mapping.get("id")
        steps.append(
            StepView(
                index=index,
                uses=uses_value if isinstance(uses_value, str) else None,
                run=run_value if isinstance(run_value, str) else None,
                step_id=step_id_value if isinstance(step_id_value, str) else None,
                with_block=parse_str_mapping(step_mapping.get("with")),
                env=parse_str_mapping(step_mapping.get("env")),
            )
        )
    return steps, problems


def parse_needs(needs_value: object) -> list[str]:
    if isinstance(needs_value, str):
        return [needs_value]
    entries = parse_object_list(needs_value)
    if entries is None:
        return []
    return [str(entry) for entry in entries]


def validate_integrate_contract(
    workflow: WorkflowView, verbs_by_job: dict[str, list[VerbStep]], path: Path
) -> list[Problem]:
    problems: list[Problem] = []
    jobs = workflow.jobs
    for root in (LINT_WORKFLOWS_JOB, VALIDATE_RELEASE_PLAN_JOB, MIRROR_IMAGES_JOB):
        if root in jobs and jobs[root].needs:
            problems.append(
                job_problem(path, root, f"is a parallel root and must carry no needs, got {jobs[root].needs}")
            )
    if PREFLIGHT_JOB in jobs:
        expected: set[str] = {root for root in (LINT_WORKFLOWS_JOB, MIRROR_IMAGES_JOB) if root in jobs}
        actual = set(jobs[PREFLIGHT_JOB].needs)
        if actual != expected:
            problems.append(
                job_problem(
                    path,
                    PREFLIGHT_JOB,
                    f"must need {sorted(expected)} (contract breaks kill the battery early), got {sorted(actual)}",
                )
            )
    pr_carriers = [
        job_name for job_name, steps in verbs_by_job.items() if any(step.channel == PR_CHANNEL for step in steps)
    ]
    if pr_carriers and pr_carriers != [UPDATE_PR_DRAFT_JOB]:
        problems.append(
            file_problem(
                path,
                f"the release verb's {PR_CHANNEL} channel must run in the '{UPDATE_PR_DRAFT_JOB}' job,"
                f" got {pr_carriers}",
            )
        )
    pr_draft_job = jobs.get(UPDATE_PR_DRAFT_JOB)
    if pr_draft_job is not None:
        if pr_draft_job.if_condition != PR_DRAFT_JOB_IF:
            problems.append(
                job_problem(
                    path,
                    UPDATE_PR_DRAFT_JOB,
                    f"must gate on if: {PR_DRAFT_JOB_IF} (the verb parses the PR number from GITHUB_REF,"
                    " which carries no refs/pull spelling on a dispatch run)",
                )
            )
        if VALIDATE_RELEASE_PLAN_JOB not in pr_draft_job.needs:
            problems.append(
                job_problem(
                    path,
                    UPDATE_PR_DRAFT_JOB,
                    f"must need {VALIDATE_RELEASE_PLAN_JOB} (contract breaks kill the battery early),"
                    f" got {pr_draft_job.needs}",
                )
            )
    return problems


def validate_release_contract(
    workflow: WorkflowView, verbs_by_job: dict[str, list[VerbStep]], path: Path
) -> list[Problem]:
    problems: list[Problem] = []
    triggers = workflow.triggers
    push = parse_str_mapping(triggers.get("push")) if triggers is not None else None
    if push is None or push.get("branches") != RELEASE_PUSH_BRANCHES:
        problems.append(
            file_problem(path, f"must trigger on push to branches {RELEASE_PUSH_BRANCHES} (the delivery events)")
        )
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != RELEASE_CONCURRENCY:
        problems.append(
            file_problem(path, f"concurrency group must be {RELEASE_CONCURRENCY} (the per-ref delivery queue)")
        )
    elif "cancel-in-progress" in concurrency:
        problems.append(
            file_problem(path, "concurrency must omit cancel-in-progress — the queue is the delivery mutex")
        )
    dev_carriers = [
        job_name for job_name, steps in verbs_by_job.items() if any(step.channel == DEV_CHANNEL for step in steps)
    ]
    if dev_carriers and dev_carriers != [PRERELEASE_JOB]:
        problems.append(
            file_problem(
                path,
                f"the release verb's {DEV_CHANNEL} channel must run in the '{PRERELEASE_JOB}' job, got {dev_carriers}",
            )
        )
    stable_carriers = [
        job_name for job_name, steps in verbs_by_job.items() if any(step.channel == STABLE_CHANNEL for step in steps)
    ]
    if stable_carriers and stable_carriers != [RELEASE_JOB]:
        problems.append(
            file_problem(
                path,
                f"the release verb's {STABLE_CHANNEL} channel must run in the '{RELEASE_JOB}' job,"
                f" got {stable_carriers}",
            )
        )
    return problems


def validate_merge_gate_triggers(workflow: WorkflowView, path: Path) -> list[Problem]:
    triggers = workflow.triggers
    pull_request = parse_str_mapping(triggers.get("pull_request")) if triggers is not None else None
    problems: list[Problem] = []
    if pull_request is None or pull_request.get("types") != ["labeled"] or pull_request.get("branches") != ["dev"]:
        problems.append(file_problem(path, "must trigger on pull_request to dev, types [labeled] only"))
    if triggers is not None and "workflow_run" in triggers:
        problems.append(file_problem(path, "workflow_run is forbidden — the labeled wake is the sole trigger"))
    return problems


def validate_merge_gate_concurrency(workflow: WorkflowView, path: Path) -> list[Problem]:
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != MERGE_GATE_CONCURRENCY:
        return [file_problem(path, f"concurrency group must be {MERGE_GATE_CONCURRENCY} (the per-PR lander queue)")]
    if "cancel-in-progress" in concurrency:
        return [file_problem(path, "concurrency must omit cancel-in-progress — serialization is the policy")]
    return []


def validate_job(job_name: str, job: JobView, path: Path, nuget: bool) -> tuple[list[Problem], list[VerbStep]]:
    problems: list[Problem] = []
    if job.has_environment:
        problems.append(job_problem(path, job_name, "environment: key is forbidden (the fleet runs environment-less)"))
    steps = job.steps
    verb_steps, verb_problems = collect_verb_steps(job_name, steps, path, nuget)
    problems.extend(verb_problems)
    stable_push_allowed = any(step.channel == STABLE_CHANNEL for step in verb_steps)
    checkout_steps, checkout_problems = collect_checkout_steps(job_name, steps, path, stable_push_allowed)
    problems.extend(checkout_problems)
    if verb_steps:
        problems.extend(validate_verb_installation(job_name, steps, path))
        problems.extend(validate_verb_checkout_needs(job_name, checkout_steps, verb_steps, path))
        problems.extend(validate_env_references(job_name, steps, verb_steps, path))
    return problems, verb_steps


def validate_verb_installation(job_name: str, steps: list[StepView], path: Path) -> list[Problem]:
    if any(step.uses == DEVKIT_WRAPPER_USES for step in steps):
        return []
    if any(step.run is not None and step.run.startswith(DEVKIT_CLONE_PREFIX) for step in steps):
        return []
    return [
        job_problem(
            path,
            job_name,
            f"a verb-carrying job must install release-devkit: one {DEVKIT_WRAPPER_USES} step"
            f" or a '{DEVKIT_CLONE_PREFIX}' clone step (the dynamic-SHA self-test shape)",
        )
    ]


def validate_verb_checkout_needs(
    job_name: str, checkout_steps: list[CheckoutStep], verb_steps: list[VerbStep], path: Path
) -> list[Problem]:
    problems: list[Problem] = []
    needs_tag_fetch = any(spec_needs_tag_fetch(step.spec) for step in verb_steps)
    needs_history = any(spec_needs_history(step.spec) for step in verb_steps)
    if needs_tag_fetch:
        if not any(
            step.with_block.get("fetch-depth") == 0 and step.with_block.get("fetch-tags") is True
            for step in checkout_steps
        ):
            problems.append(
                job_problem(
                    path,
                    job_name,
                    "tag-consuming verbs need a checkout with fetch-depth: 0 and fetch-tags: true in the job",
                )
            )
    elif needs_history and not any(step.with_block.get("fetch-depth") == 0 for step in checkout_steps):
        problems.append(job_problem(path, job_name, "merge-gate needs a checkout with fetch-depth: 0 in the job"))
    return problems


def validate_env_references(
    job_name: str, steps: list[StepView], verb_steps: list[VerbStep], path: Path
) -> list[Problem]:
    step_ids = {step.step_id for step in steps if step.step_id is not None}
    problems: list[Problem] = []
    for verb_step in verb_steps:
        step = next(step for step in steps if step.index == verb_step.step_index)
        env = step.env if step.env is not None else {}
        for key, value in env.items():
            match = ENV_STEP_REFERENCE.search(str(value))
            if match is not None and match.group(1) not in step_ids:
                problems.append(
                    step_problem(
                        path,
                        job_name,
                        verb_step.step_index,
                        f"env {key} references step '{match.group(1)}' but the job has no step with that id",
                    )
                )
    return problems


def collect_verb_steps(
    job_name: str, steps: list[StepView], path: Path, nuget: bool
) -> tuple[list[VerbStep], list[Problem]]:
    verb_steps: list[VerbStep] = []
    problems: list[Problem] = []
    for step in steps:
        run_value = step.run
        if run_value is None or DEVKIT_INVOCATION_PREFIX not in run_value:
            continue
        segments = [segment.strip() for segment in SHELL_STATEMENT_SPLIT.split(run_value) if segment.strip()]
        for segment in segments:
            match = DEVKIT_INVOCATION.fullmatch(segment)
            if match is None:
                problems.append(
                    step_problem(
                        path,
                        job_name,
                        step.index,
                        "executes a release-devkit verb;"
                        f" the step must consist solely of canonical {DEVKIT_INVOCATION_PREFIX.strip()}<verb>"
                        " invocations",
                    )
                )
                break
            verb = match.group("verb")
            args = match.group("args")
            if verb == RELEASE_VERB:
                channel, spec = resolve_channel(args)
                if spec is None:
                    problems.append(
                        step_problem(path, job_name, step.index, f"{verb} carries rejected arguments ({args.strip()})")
                    )
                    continue
            else:
                channel = None
                spec = VERB_SPECS[verb]
                if not spec.args.fullmatch(args):
                    problems.append(
                        step_problem(path, job_name, step.index, f"{verb} carries rejected arguments ({args.strip()})")
                    )
                    continue
            verb_step = VerbStep(step_index=step.index, name=verb, args=args, channel=channel, spec=spec)
            problems.extend(validate_verb_env(job_name, verb_step, step, path, nuget))
            verb_steps.append(verb_step)
    return verb_steps, problems


def resolve_channel(args: str) -> tuple[str | None, ChannelSpec | None]:
    for channel, spec in RELEASE_CHANNELS.items():
        if spec.args.fullmatch(args):
            return channel, spec
    return None, None


def spec_needs_tag_fetch(spec: VerbSpec | ChannelSpec) -> bool:
    return isinstance(spec, ChannelSpec) or spec.needs_tag_fetch


def spec_needs_history(spec: VerbSpec | ChannelSpec) -> bool:
    return isinstance(spec, VerbSpec) and spec.needs_history


def verb_label(verb_step: VerbStep) -> str:
    if verb_step.channel is None:
        return verb_step.name
    return f"{verb_step.name} --channel {verb_step.channel}"


def validate_verb_env(job_name: str, verb_step: VerbStep, step: StepView, path: Path, nuget: bool) -> list[Problem]:
    problems: list[Problem] = []
    label = verb_label(verb_step)
    env = step.env if step.env is not None else {}
    expected = spec_env(verb_step)
    for key, value in expected.items():
        if env.get(key) != value:
            problems.append(step_problem(path, job_name, verb_step.step_index, f"{label} requires env {key}: {value}"))
    if verb_step.spec.delivery:
        api_key_value = env.get(NUGET_API_KEY_ENV)
        if nuget and api_key_value != NUGET_API_KEY_SOURCE:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    verb_step.step_index,
                    f"{label} requires env {NUGET_API_KEY_ENV}: {NUGET_API_KEY_SOURCE}",
                )
            )
        if not nuget and api_key_value is not None:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    verb_step.step_index,
                    f"{label} must not carry {NUGET_API_KEY_ENV} env"
                    " (the release-devkit.yaml declares no nuget registry)",
                )
            )
    return problems


def spec_env(verb_step: VerbStep) -> dict[str, str]:
    spec = verb_step.spec
    if isinstance(spec, VerbSpec) and spec.dry_run_env is not None:
        return spec.dry_run_env if verb_step.args.endswith(DRY_RUN_SUFFIX) else spec.env
    return spec.env


def collect_checkout_steps(
    job_name: str, steps: list[StepView], path: Path, stable_push_allowed: bool
) -> tuple[list[CheckoutStep], list[Problem]]:
    checkout_steps: list[CheckoutStep] = []
    problems: list[Problem] = []
    for step in steps:
        uses_value = step.uses
        if uses_value is None:
            continue
        if uses_value != CHECKOUT_USES and not uses_value.startswith("actions/checkout"):
            continue
        if uses_value != CHECKOUT_USES:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step.index,
                    f"checkout must be {CHECKOUT_USES} (the SHA-pinned wrapper), got {uses_value}",
                )
            )
            continue
        with_block = step.with_block if step.with_block is not None else {}
        checkout_steps.append(CheckoutStep(step_index=step.index, with_block=with_block))
        if path.name not in REF_LAWS:
            continue
        ref_law = REF_LAWS[path.name]
        if ref_law is None:
            if "ref" in with_block:
                problems.append(
                    step_problem(
                        path,
                        job_name,
                        step.index,
                        "release.yml checkouts must carry no ref (they check out what was pushed;"
                        f" a spelled branch races the delivery queue), got {with_block['ref']}",
                    )
                )
        elif with_block.get("ref") != ref_law:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step.index,
                    f"checkout ref must be {ref_law}, got {with_block.get('ref')}",
                )
            )
        persist = with_block.get("persist-credentials")
        is_stable_push_form = (
            persist is True and with_block.get("fetch-depth") == 0 and with_block.get("fetch-tags") is True
        )
        if persist is not False and not (stable_push_allowed and is_stable_push_form):
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step.index,
                    "checkout must set persist-credentials: false"
                    " (only the stable release job's tag-fetching push checkout may persist)",
                )
            )
    return checkout_steps, problems


def is_cache_writing_setup_uv(step: StepView) -> bool:
    if step.uses != SETUP_UV_USES:
        return False
    with_block = step.with_block
    if with_block is None:
        return False
    return with_block.get("enable-cache") is True and with_block.get("save-cache") != "false"


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


def job_problem(path: Path, job: str, message: str) -> Problem:
    return Problem(path=path, message=message, job=job)


def step_problem(path: Path, job: str, step_index: int, message: str) -> Problem:
    return Problem(path=path, message=message, job=job, step_index=step_index)


def render_problem(problem: Problem) -> str:
    location = str(problem.path)
    if problem.job is not None:
        location += f": job '{problem.job}'"
        if problem.step_index is not None:
            location += f" step {problem.step_index}"
    return f"{location}: {problem.message}"


def rendered(problems: list[Problem]) -> list[str]:
    return [render_problem(problem) for problem in problems]
