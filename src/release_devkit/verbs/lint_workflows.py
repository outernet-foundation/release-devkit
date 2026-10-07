from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import TypeAdapter, ValidationError

from release_devkit.actionlint import run_actionlint
from release_devkit.config import load_config

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ROOT_DOCUMENT = TypeAdapter(dict[object, object])
STR_MAPPING = TypeAdapter(dict[str, object])
OBJECT_LIST = TypeAdapter(list[object])

CHECKOUT_USES = "actions/checkout@v5"
DEVKIT_WRAPPER_USES = "./.github/actions/setup-release-devkit"
DEVKIT_WRAPPER_PATH = Path(".github/actions/setup-release-devkit/action.yml")
DEVKIT_REPOSITORY = "outernet-foundation/release-devkit"
DEVKIT_INSTALL_PATH = "$RUNNER_TEMP/release-devkit"
DEVKIT_INVOCATION_PREFIX = f'uv run --project "{DEVKIT_INSTALL_PATH}" --locked --no-dev '
SETUP_UV_USES = "astral-sh/setup-uv@v7"
CONFIG_PATH = Path("release-devkit.yaml")
INTEGRATE_HEAD_SHA = "${{ github.event.pull_request.head.sha }}"
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
NUGET_LOGIN_USES = "NuGet/login@v1"
NUGET_LOGIN_INPUTS = {"user": "${{ secrets.NUGET_USER }}"}
NUGET_API_KEY_ENV = "NUGET_API_KEY"
NUGET_API_KEY_SOURCE = "${{ steps.nuget-login.outputs.NUGET_API_KEY }}"
NUGET_DELIVERY_VERBS = ("prerelease", "release")
INTEGRATE_WORKFLOW = Path(".github/workflows/integrate.yml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
RELEASE_WORKFLOW_NAME = "Release"
RELEASE_CONCURRENCY = "release-${{ github.ref }}"
MERGE_GATE_WORKFLOW = Path(".github/workflows/merge-gate.yml")
LINT_WORKFLOWS_JOB = "lint-workflows"
VALIDATE_RELEASE_PLAN_JOB = "validate-release-plan"
PREFLIGHT_JOB = "preflight"
MIRROR_IMAGES_JOB = "mirror-images"
RELEASE_JOB = "release"

DEAD_USES_PREFIXES = ("./.release-devkit/", "./.github/actions/checkout-release-devkit")

CHECKOUT = "checkout"
CHECKOUT_WITH_TAGS = "checkout-with-tags"
CHECKOUT_WITH_TAGS_PUSH = "checkout-with-tags-push"
MERGE_BOT = "merge-bot"

VERB_CHECKOUTS: dict[str, str] = {
    "get-app-version": CHECKOUT_WITH_TAGS,
    "release": CHECKOUT_WITH_TAGS_PUSH,
    "prerelease": CHECKOUT_WITH_TAGS,
    "lint-workflows": CHECKOUT,
    "merge-gate": MERGE_BOT,
    "validate-release-plan": CHECKOUT_WITH_TAGS,
    "update-pr-draft-release": CHECKOUT_WITH_TAGS,
}

SETUP_UV_RESTORE_INPUTS = {"enable-cache": True, "save-cache": "false"}
SETUP_UV_SAVE_INPUTS = {"enable-cache": True, "save-cache": "true"}

WRAPPER_COMMIT_ENV_VAR = "RELEASE_DEVKIT_COMMIT"
WRAPPER_COMMIT_ENV = re.compile(r"^[0-9a-f]{40}$")
WRAPPER_CLONE = re.compile(
    r"^git clone https://github\.com/outernet-foundation/release-devkit\.git"
    r' "\$RUNNER_TEMP/release-devkit"'
    rf'\ngit -C "\$RUNNER_TEMP/release-devkit" checkout "\${WRAPPER_COMMIT_ENV_VAR}"$'
)
DEVKIT_INVOCATION = re.compile(
    re.escape(DEVKIT_INVOCATION_PREFIX) + r"(?P<verb>get-app-version|release|prerelease|lint-workflows|merge-gate"
    r"|validate-release-plan|update-pr-draft-release)" + r'(?P<args>(?: [^)"]*)?)'
)
VERB_ARGS: dict[str, re.Pattern[str]] = {
    "get-app-version": re.compile(r"^ --app \S+$"),
    "release": re.compile(r"^$"),
    "prerelease": re.compile(r"^$"),
    "lint-workflows": re.compile(r"^$"),
    "merge-gate": re.compile(r"^ --head-sha .+$"),
    "validate-release-plan": re.compile(r"^$"),
    "update-pr-draft-release": re.compile(r"^$"),
}
VERB_ENV: dict[str, dict[str, str]] = {
    "release": {"GITHUB_TOKEN": "${{ github.token }}"},
    "prerelease": {"GITHUB_TOKEN": "${{ github.token }}"},
    "merge-gate": {
        "GITHUB_TOKEN": "${{ steps.mint.outputs.token }}",
    },
    "validate-release-plan": {},
    "update-pr-draft-release": {"GITHUB_TOKEN": "${{ github.token }}"},
}

RUN_STEP_LINE = re.compile(r"^(?P<prefix>\s*(?:- )?)run:(?:\s*(?P<value>.*))?$")
BLOCK_SCALAR_HEAD = re.compile(r"^[|>](?:[+-]\d?|\d[+-]?)$")
RUN_STEP_FOLD_THRESHOLD = 120


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
    signature: str


@dataclass
class VerbStep:
    step_index: int
    name: str


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str
    job: str | None = None
    step_index: int | None = None
    line_number: int | None = None


@dataclass(frozen=True)
class RepoContext:
    publishing: bool
    nuget: bool


@app.command()
def main(
    workflows: Annotated[
        list[Path] | None,
        typer.Option(
            "--workflow",
            help="Workflow file to signature-validate (repeatable; default integrate + release + merge-gate)",
        ),
    ] = None,
) -> None:
    workflow_paths = workflows or default_workflows()
    problems: list[str] = []
    for workflow_path in workflow_paths:
        problems.extend(validate_workflow_file(workflow_path, publishing=is_publishing(), nuget=declares_nuget()))
    problems.extend(validate_devkit_wrapper())
    for problem in problems:
        print(problem)
    run_actionlint()
    if problems:
        raise SystemExit(1)


def default_workflows() -> list[Path]:
    workflows = [INTEGRATE_WORKFLOW]
    if is_publishing():
        workflows.append(RELEASE_WORKFLOW)
    workflows.append(MERGE_GATE_WORKFLOW)
    return workflows


def is_publishing() -> bool:
    return CONFIG_PATH.is_file()


def declares_nuget() -> bool:
    if not CONFIG_PATH.is_file():
        return False
    config = load_config(CONFIG_PATH)
    return any(package.registry == "nuget" for package in config.packages.values())


def validate_devkit_wrapper(path: Path = DEVKIT_WRAPPER_PATH) -> list[str]:
    if not path.is_file():
        return rendered([file_problem(path, "wrapper action not found")])
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


def validate_workflow_file(path: Path, publishing: bool = True, nuget: bool = False) -> list[str]:
    if not path.is_file():
        return rendered([file_problem(path, "workflow file not found")])
    context = RepoContext(publishing=publishing, nuget=nuget)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    document: object = yaml.safe_load("\n".join(raw_lines))
    workflow, problems = parse_workflow(path, document)
    if workflow is None:
        return rendered(problems)
    verbs_by_job: dict[str, list[str]] = {}
    for job_name, job in workflow.jobs.items():
        job_problems, verb_steps = validate_job(job_name, job, path, context)
        problems.extend(job_problems)
        verbs_by_job[job_name] = [verb.name for verb in verb_steps]
    problems.extend(validate_run_steps_single_line(raw_lines, path))
    if path.name == "integrate.yml":
        problems.extend(validate_integrate_contract(workflow, verbs_by_job, context, path))
    if path.name == "release.yml":
        problems.extend(validate_release_contract(workflow, verbs_by_job, path))
    if path.name == "merge-gate.yml":
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
    workflow: WorkflowView, verbs_by_job: dict[str, list[str]], context: RepoContext, path: Path
) -> list[Problem]:
    problems: list[Problem] = []
    jobs = workflow.jobs
    if context.publishing and VALIDATE_RELEASE_PLAN_JOB not in jobs:
        problems.append(
            file_problem(
                path,
                f"publishing repos must run the {VALIDATE_RELEASE_PLAN_JOB} job (release-devkit.yaml is present)",
            )
        )
    if LINT_WORKFLOWS_JOB not in jobs:
        problems.append(file_problem(path, f"integrate.yml must run the {LINT_WORKFLOWS_JOB} job (the lint root)"))
    for verb_job in (LINT_WORKFLOWS_JOB, VALIDATE_RELEASE_PLAN_JOB):
        carrying = [job_name for job_name, verbs in verbs_by_job.items() if verb_job in verbs]
        if carrying and carrying != [verb_job]:
            problems.append(file_problem(path, f"the {verb_job} verb must run in the '{verb_job}' job, got {carrying}"))
    for root in (LINT_WORKFLOWS_JOB, VALIDATE_RELEASE_PLAN_JOB, MIRROR_IMAGES_JOB):
        needs = jobs[root].needs if root in jobs else []
        if needs:
            problems.append(job_problem(path, root, f"is a parallel root and must carry no needs, got {needs}"))
    if PREFLIGHT_JOB in jobs:
        expected: set[str] = {LINT_WORKFLOWS_JOB}
        if MIRROR_IMAGES_JOB in jobs:
            expected.add(MIRROR_IMAGES_JOB)
        actual = set(jobs[PREFLIGHT_JOB].needs)
        if actual != expected:
            problems.append(
                job_problem(
                    path,
                    PREFLIGHT_JOB,
                    f"must need {sorted(expected)} (contract breaks kill the battery early), got {sorted(actual)}",
                )
            )
    writer_jobs = [job_name for job_name, job in jobs.items() if job_has_cache_writing_setup_uv(job)]
    expected_writer = PREFLIGHT_JOB if PREFLIGHT_JOB in jobs else LINT_WORKFLOWS_JOB
    if len(writer_jobs) != 1:
        problems.append(
            file_problem(
                path,
                f"integrate.yml must carry exactly one cache-writing setup-uv step ({expected_writer}'s saver),"
                f" found {len(writer_jobs)}",
            )
        )
    elif writer_jobs != [expected_writer]:
        problems.append(
            file_problem(path, f"the cache-writing setup-uv must live in '{expected_writer}', found {writer_jobs}")
        )
    return problems


def validate_release_contract(workflow: WorkflowView, verbs_by_job: dict[str, list[str]], path: Path) -> list[Problem]:
    problems: list[Problem] = []
    if workflow.name != RELEASE_WORKFLOW_NAME:
        problems.append(file_problem(path, f"workflow name must be {RELEASE_WORKFLOW_NAME}"))
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != RELEASE_CONCURRENCY:
        problems.append(
            file_problem(path, f"concurrency group must be {RELEASE_CONCURRENCY} (the per-ref delivery queue)")
        )
    elif "cancel-in-progress" in concurrency:
        problems.append(
            file_problem(path, "concurrency must omit cancel-in-progress — the queue is the delivery mutex")
        )
    carrying = [job_name for job_name, verbs in verbs_by_job.items() if RELEASE_JOB in verbs]
    if carrying and carrying != [RELEASE_JOB]:
        problems.append(file_problem(path, f"the release verb must run in the '{RELEASE_JOB}' job, got {carrying}"))
    return problems


def validate_merge_gate_triggers(workflow: WorkflowView, path: Path) -> list[Problem]:
    triggers = workflow.triggers
    pull_request = parse_str_mapping(triggers.get("pull_request")) if triggers is not None else None
    workflow_run = parse_str_mapping(triggers.get("workflow_run")) if triggers is not None else None
    problems: list[Problem] = []
    if pull_request is None or pull_request.get("types") != ["labeled"] or pull_request.get("branches") != ["dev"]:
        problems.append(file_problem(path, "must trigger on pull_request to dev, types [labeled] only"))
    if (
        workflow_run is None
        or workflow_run.get("workflows") != ["Integrate"]
        or workflow_run.get("types") != ["completed"]
    ):
        problems.append(file_problem(path, "must trigger on workflow_run from Integrate, types [completed] only"))
    return problems


def validate_merge_gate_concurrency(workflow: WorkflowView, path: Path) -> list[Problem]:
    concurrency = workflow.concurrency
    if concurrency is None or concurrency.get("group") != MERGE_GATE_CONCURRENCY:
        return [
            file_problem(path, f"concurrency group must be {MERGE_GATE_CONCURRENCY} (the || fallback is load-bearing)")
        ]
    if "cancel-in-progress" in concurrency:
        return [file_problem(path, "concurrency must omit cancel-in-progress — serialization is the policy")]
    return []


def validate_job(job_name: str, job: JobView, path: Path, context: RepoContext) -> tuple[list[Problem], list[VerbStep]]:
    problems: list[Problem] = []
    if job.has_environment:
        problems.append(job_problem(path, job_name, "environment: key is forbidden (the fleet runs environment-less)"))
    steps = job.steps
    checkout_steps, checkout_problems = collect_checkout_steps(job_name, steps, path)
    problems.extend(checkout_problems)
    verb_steps, verb_problems = collect_verb_steps(job_name, steps, path, context)
    problems.extend(verb_problems)
    problems.extend(collect_dead_uses(job_name, steps, path))
    if not verb_steps:
        return problems, verb_steps
    problems.extend(validate_reserved_checkouts(job_name, checkout_steps, verb_steps, path))
    first_verb_index = min(verb.step_index for verb in verb_steps)
    earliest_wrapper_index, wrapper_problems = validate_wrapper_precedes_verb(job_name, steps, first_verb_index, path)
    problems.extend(wrapper_problems)
    if earliest_wrapper_index is None:
        return problems, verb_steps
    problems.extend(
        validate_checkouts_precede_wrapper(job_name, checkout_steps, verb_steps, earliest_wrapper_index, path)
    )
    problems.extend(validate_setup_uv_precedes_wrapper(job_name, steps, earliest_wrapper_index, path))
    problems.extend(
        validate_mint_window(job_name, steps, verb_steps, first_verb_index, earliest_wrapper_index, path, context)
    )
    return problems, verb_steps


def validate_reserved_checkouts(
    job_name: str, checkout_steps: list[CheckoutStep], verb_steps: list[VerbStep], path: Path
) -> list[Problem]:
    problems: list[Problem] = []
    is_release_job = any(verb.name == "release" for verb in verb_steps)
    is_merge_gate_job = any(verb.name == "merge-gate" for verb in verb_steps)
    if not is_release_job and any(step.signature == CHECKOUT_WITH_TAGS_PUSH for step in checkout_steps):
        problems.append(job_problem(path, job_name, "checkout-with-tags-push is reserved for release jobs"))
    if not is_merge_gate_job and any(step.signature == MERGE_BOT for step in checkout_steps):
        problems.append(job_problem(path, job_name, "merge-bot checkout is reserved for merge-gate jobs"))
    return problems


def validate_wrapper_precedes_verb(
    job_name: str, steps: list[StepView], first_verb_index: int, path: Path
) -> tuple[int | None, list[Problem]]:
    wrapper_indexes = [step.index for step in steps if step.uses == DEVKIT_WRAPPER_USES]
    wrappers_before = [index for index in wrapper_indexes if index < first_verb_index]
    if not wrappers_before:
        return None, [job_problem(path, job_name, f"no {DEVKIT_WRAPPER_USES} step precedes the release-devkit verb")]
    return min(wrappers_before), []


def validate_checkouts_precede_wrapper(
    job_name: str,
    checkout_steps: list[CheckoutStep],
    verb_steps: list[VerbStep],
    earliest_wrapper_index: int,
    path: Path,
) -> list[Problem]:
    problems: list[Problem] = []
    required_checkouts = {VERB_CHECKOUTS[verb.name] for verb in verb_steps}
    for required in sorted(required_checkouts):
        if not any(step.signature == required and step.step_index < earliest_wrapper_index for step in checkout_steps):
            problems.append(
                job_problem(path, job_name, f"no {required} checkout precedes the setup-release-devkit step")
            )
    return problems


def validate_setup_uv_precedes_wrapper(
    job_name: str, steps: list[StepView], earliest_wrapper_index: int, path: Path
) -> list[Problem]:
    if any(is_canonical_setup_uv(step) and step.index < earliest_wrapper_index for step in steps):
        return []
    return [
        job_problem(
            path,
            job_name,
            f"no canonical {SETUP_UV_USES} step"
            " (enable-cache: true with an explicit save-cache) precedes the setup-release-devkit step",
        )
    ]


def validate_mint_window(
    job_name: str,
    steps: list[StepView],
    verb_steps: list[VerbStep],
    first_verb_index: int,
    earliest_wrapper_index: int,
    path: Path,
    context: RepoContext,
) -> list[Problem]:
    problems: list[Problem] = []
    is_merge_gate_job = any(verb.name == "merge-gate" for verb in verb_steps)
    is_delivery_job = any(verb.name in NUGET_DELIVERY_VERBS for verb in verb_steps)
    mint_indexes, mint_problems = canonical_mint_steps(
        job_name,
        steps,
        MINT_STEP_USES,
        "mint",
        MINT_STEP_INPUTS,
        path,
        "create-github-app-token must be the canonical mint step"
        " (id: mint, app-id from the MERGE_BOT_APP_ID var, private-key from the MERGE_BOT_APP_PRIVATE_KEY secret)",
    )
    problems.extend(mint_problems)
    if is_merge_gate_job and not steps_in_window(mint_indexes, earliest_wrapper_index, first_verb_index):
        problems.append(
            job_problem(
                path,
                job_name,
                f"merge-gate requires a canonical {MINT_STEP_USES} mint step between the wrapper and the verb",
            )
        )
    nuget_login_indexes, nuget_login_problems = canonical_mint_steps(
        job_name,
        steps,
        NUGET_LOGIN_USES,
        "nuget-login",
        NUGET_LOGIN_INPUTS,
        path,
        "NuGet/login must be the canonical mint step (id: nuget-login, user from the NUGET_USER org secret)",
    )
    problems.extend(nuget_login_problems)
    if (
        is_delivery_job
        and context.nuget
        and not steps_in_window(nuget_login_indexes, earliest_wrapper_index, first_verb_index)
    ):
        problems.append(
            job_problem(
                path,
                job_name,
                f"nuget delivery jobs require a canonical {NUGET_LOGIN_USES} mint step"
                " between the wrapper and the verb",
            )
        )
    if not is_delivery_job or not context.nuget:
        if any(step.uses == NUGET_LOGIN_USES for step in steps):
            problems.append(
                job_problem(
                    path,
                    job_name,
                    f"{NUGET_LOGIN_USES} is reserved for the delivery jobs"
                    " of repos whose release-devkit.yaml declares a nuget registry",
                )
            )
    return problems


def canonical_mint_steps(
    job_name: str, steps: list[StepView], uses: str, step_id: str, inputs: dict[str, str], path: Path, message: str
) -> tuple[list[int], list[Problem]]:
    indexes: list[int] = []
    problems: list[Problem] = []
    for step in steps:
        if step.uses != uses:
            continue
        if step.step_id != step_id or step.with_block != inputs:
            problems.append(step_problem(path, job_name, step.index, message))
            continue
        indexes.append(step.index)
    return indexes, problems


def steps_in_window(indexes: list[int], earliest_wrapper_index: int, first_verb_index: int) -> bool:
    return any(earliest_wrapper_index < index < first_verb_index for index in indexes)


def job_has_cache_writing_setup_uv(job: JobView) -> bool:
    return any(is_cache_writing_setup_uv(step) for step in job.steps)


def validate_run_steps_single_line(raw_lines: list[str], path: Path) -> list[Problem]:
    # the single-line rule is about physical lines, which the parsed YAML value cannot see — hence this raw-text pass
    problems: list[Problem] = []
    for index, line in enumerate(raw_lines):
        match = RUN_STEP_LINE.match(line)
        if not match:
            continue
        value = (match.group("value") or "").strip()
        run_column = len(line) - len(line.lstrip()) + len(match.group("prefix").lstrip())
        if not value or BLOCK_SCALAR_HEAD.fullmatch(value):
            if value == ">-":
                block: list[str] = []
                for entry in raw_lines[index + 1 :]:
                    if entry.strip() and len(entry) - len(entry.lstrip()) <= run_column:
                        break
                    block.append(entry)
                stripped = [entry.strip() for entry in block if entry.strip()]
                if len(stripped) != len(block):
                    problems.append(
                        line_problem(
                            path,
                            index + 1,
                            "run: steps must be a single physical line (folded blocks may not contain blank lines)",
                        )
                    )
                elif not stripped:
                    problems.append(
                        line_problem(path, index + 1, "run: steps must be a single physical line (empty folded block)")
                    )
                elif len({len(entry) - len(entry.lstrip()) for entry in block}) != 1:
                    problems.append(
                        line_problem(
                            path,
                            index + 1,
                            "run: steps must be a single physical line (folded continuations must share one indent)",
                        )
                    )
                else:
                    joined = " ".join(stripped)
                    if len(joined) <= RUN_STEP_FOLD_THRESHOLD:
                        problems.append(
                            line_problem(
                                path,
                                index + 1,
                                "run: steps must be a single physical line (folds are allowed only for commands"
                                f" longer than {RUN_STEP_FOLD_THRESHOLD} characters)",
                            )
                        )
                    elif "release-devkit" in joined:
                        problems.append(
                            line_problem(
                                path,
                                index + 1,
                                "run: steps must be a single physical line (devkit verb invocations never fold)",
                            )
                        )
            else:
                problems.append(
                    line_problem(
                        path, index + 1, "run: steps must be a single physical line (no folded or literal blocks)"
                    )
                )
            continue
        follow_up = next((entry for entry in raw_lines[index + 1 :] if entry.strip()), "")
        if follow_up and len(follow_up) - len(follow_up.lstrip()) > run_column:
            problems.append(
                line_problem(path, index + 1, "run: steps must be a single physical line (folded continuation follows)")
            )
    return problems


def is_canonical_setup_uv(step: StepView) -> bool:
    if step.uses != SETUP_UV_USES:
        return False
    with_block = step.with_block
    if with_block is None:
        return False
    return any(with_block == inputs for inputs in (SETUP_UV_RESTORE_INPUTS, SETUP_UV_SAVE_INPUTS))


def is_cache_writing_setup_uv(step: StepView) -> bool:
    if step.uses != SETUP_UV_USES:
        return False
    with_block = step.with_block
    if with_block is None:
        return False
    return with_block.get("enable-cache") is True and with_block.get("save-cache") != "false"


def collect_dead_uses(job_name: str, steps: list[StepView], path: Path) -> list[Problem]:
    problems: list[Problem] = []
    for step in steps:
        uses_value = step.uses
        if uses_value is not None and uses_value.startswith(DEAD_USES_PREFIXES):
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step.index,
                    f"{uses_value} is the dead composite-action model;"
                    " verbs are plain run steps against $RUNNER_TEMP/release-devkit",
                )
            )
    return problems


def collect_verb_steps(
    job_name: str, steps: list[StepView], path: Path, context: RepoContext
) -> tuple[list[VerbStep], list[Problem]]:
    verb_steps: list[VerbStep] = []
    problems: list[Problem] = []
    for step in steps:
        run_value = step.run
        if run_value is None or DEVKIT_INSTALL_PATH not in run_value:
            continue
        prefix_count = run_value.count(DEVKIT_INVOCATION_PREFIX)
        matches = list(DEVKIT_INVOCATION.finditer(run_value))
        if not prefix_count or len(matches) != prefix_count:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step.index,
                    f"mentions {DEVKIT_INSTALL_PATH} without a canonical"
                    f" {DEVKIT_INVOCATION_PREFIX.strip()}<verb> invocation",
                )
            )
            continue
        for match in matches:
            verb = match.group("verb")
            args = match.group("args")
            if not VERB_ARGS[verb].fullmatch(args):
                problems.append(
                    step_problem(path, job_name, step.index, f"{verb} carries rejected arguments ({args.strip()})")
                )
                continue
            problems.extend(validate_verb_env(job_name, step.index, verb, step, path, context))
            verb_steps.append(VerbStep(step_index=step.index, name=verb))
    return verb_steps, problems


def validate_verb_env(
    job_name: str, step_index: int, verb: str, step: StepView, path: Path, context: RepoContext
) -> list[Problem]:
    problems: list[Problem] = []
    env = step.env if step.env is not None else {}
    for key, value in VERB_ENV.get(verb, {}).items():
        if env.get(key) != value:
            problems.append(step_problem(path, job_name, step_index, f"{verb} requires env {key}: {value}"))
    if verb in NUGET_DELIVERY_VERBS:
        api_key_value = env.get(NUGET_API_KEY_ENV)
        if context.nuget and api_key_value != NUGET_API_KEY_SOURCE:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step_index,
                    f"{verb} requires env {NUGET_API_KEY_ENV}: {NUGET_API_KEY_SOURCE}",
                )
            )
        if not context.nuget and api_key_value is not None:
            problems.append(
                step_problem(
                    path,
                    job_name,
                    step_index,
                    f"{verb} must not carry {NUGET_API_KEY_ENV} env"
                    " (the release-devkit.yaml declares no nuget registry)",
                )
            )
    return problems


def collect_checkout_steps(
    job_name: str, steps: list[StepView], path: Path
) -> tuple[list[CheckoutStep], list[Problem]]:
    checkout_steps: list[CheckoutStep] = []
    problems: list[Problem] = []
    for step in steps:
        uses_value = step.uses
        if uses_value is None or not uses_value.startswith("actions/checkout"):
            continue
        if uses_value != CHECKOUT_USES:
            problems.append(
                step_problem(path, job_name, step.index, f"checkout must be {CHECKOUT_USES}, got {uses_value}")
            )
            continue
        with_block = step.with_block if step.with_block is not None else {}
        signature = next((name for name, expected in signatures_for(path).items() if with_block == expected), None)
        if signature is None:
            with_json = json.dumps(with_block, sort_keys=True)
            problems.append(
                step_problem(path, job_name, step.index, f"checkout matches no signature; with={with_json}")
            )
        else:
            checkout_steps.append(CheckoutStep(step_index=step.index, signature=signature))
    return checkout_steps, problems


def signatures_for(path: Path) -> dict[str, dict[str, object]]:
    checkout_ref: dict[str, object] = {} if path.name == RELEASE_WORKFLOW.name else {"ref": INTEGRATE_HEAD_SHA}
    return {
        CHECKOUT: {**checkout_ref, "persist-credentials": False},
        CHECKOUT_WITH_TAGS: {**checkout_ref, "fetch-depth": 0, "fetch-tags": True, "persist-credentials": False},
        CHECKOUT_WITH_TAGS_PUSH: {
            **checkout_ref,
            "fetch-depth": 0,
            "fetch-tags": True,
            "persist-credentials": True,
        },
        MERGE_BOT: {"ref": MERGE_BOT_REF, "fetch-depth": 0, "persist-credentials": False},
    }


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


def line_problem(path: Path, line_number: int, message: str) -> Problem:
    return Problem(path=path, message=message, line_number=line_number)


def render_problem(problem: Problem) -> str:
    if problem.line_number is not None:
        return f"{problem.path}: line {problem.line_number}: {problem.message}"
    location = str(problem.path)
    if problem.job is not None:
        location += f": job '{problem.job}'"
        if problem.step_index is not None:
            location += f" step {problem.step_index}"
    return f"{location}: {problem.message}"


def rendered(problems: list[Problem]) -> list[str]:
    return [render_problem(problem) for problem in problems]
