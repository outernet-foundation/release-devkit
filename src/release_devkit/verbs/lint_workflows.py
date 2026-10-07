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

from release_devkit.config import load_config

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ACTIONLINT_VERSION = "1.7.12"
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
BLOCK_SCALAR_HEADS = {"|", ">", "|-", ">-", "|+", ">+", "|1", ">1", "|2", ">2", "|3", ">3", "|4", ">4"}
RUN_STEP_FOLD_THRESHOLD = 120

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
    if len(steps) != 1 or not is_mapping(steps[0]):
        return [f"{path}: wrapper must contain exactly one step (the clone)"]
    problems: list[str] = []
    if steps[0].get("shell") != "bash":
        problems.append(f"{path}: wrapper step must set shell: bash")
    env_value = steps[0].get("env")
    if (
        not is_string_mapping(env_value)
        or list(env_value) != [WRAPPER_COMMIT_ENV_VAR]
        or not WRAPPER_COMMIT_ENV.fullmatch(str(env_value[WRAPPER_COMMIT_ENV_VAR]))
    ):
        problems.append(f"{path}: wrapper step must carry the pinned commit in env {WRAPPER_COMMIT_ENV_VAR}")
    run_value = steps[0].get("run")
    if not isinstance(run_value, str) or not WRAPPER_CLONE.fullmatch(run_value.strip()):
        problems.append(
            f"{path}: wrapper step must clone {DEVKIT_REPOSITORY} into {DEVKIT_INSTALL_PATH}"
            " and checkout the pinned commit"
        )
    return problems


def validate_workflow_file(path: Path, publishing: bool = True, nuget: bool = False) -> list[str]:
    if not path.is_file():
        return [f"{path}: workflow file not found"]
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    document: object = yaml.safe_load("\n".join(raw_lines))
    if not is_mapping(document):
        return [f"{path}: workflow is not a YAML mapping"]
    jobs_value = document.get("jobs")
    if not is_mapping(jobs_value):
        return [f"{path}: no jobs mapping"]
    problems: list[str] = []
    verbs_by_job: dict[str, list[str]] = {}
    for job_name, job_value in jobs_value.items():
        job_problems, verb_steps = validate_job(str(job_name), job_value, path, nuget)
        problems.extend(job_problems)
        verbs_by_job[str(job_name)] = [verb.name for verb in verb_steps]
    problems.extend(validate_run_steps_single_line(raw_lines, path))
    if path.name == "integrate.yml":
        problems.extend(validate_integrate_contract(jobs_value, verbs_by_job, publishing, path))
    if path.name == "release.yml":
        problems.extend(validate_release_contract(document, verbs_by_job, path))
    if path.name == "merge-gate.yml":
        problems.extend(validate_merge_gate_triggers(document, path))
        problems.extend(validate_merge_gate_concurrency(document, path))
        for job_name, job_value in jobs_value.items():
            if is_mapping(job_value) and job_value.get("if") != MERGE_GATE_JOB_IF:
                problems.append(f"{path}: job '{job_name}': merge-gate.yml jobs must gate on if: {MERGE_GATE_JOB_IF}")
    return problems


def validate_integrate_contract(
    jobs_value: dict[object, object], verbs_by_job: dict[str, list[str]], publishing: bool, path: Path
) -> list[str]:
    problems: list[str] = []
    if publishing and VALIDATE_RELEASE_PLAN_JOB not in jobs_value:
        problems.append(
            f"{path}: publishing repos must run the {VALIDATE_RELEASE_PLAN_JOB} job (release-devkit.yaml is present)"
        )
    if LINT_WORKFLOWS_JOB not in jobs_value:
        problems.append(f"{path}: integrate.yml must run the {LINT_WORKFLOWS_JOB} job (the lint root)")
    for verb_job in (LINT_WORKFLOWS_JOB, VALIDATE_RELEASE_PLAN_JOB):
        carrying = [job_name for job_name, verbs in verbs_by_job.items() if verb_job in verbs]
        if carrying and carrying != [verb_job]:
            problems.append(f"{path}: the {verb_job} verb must run in the '{verb_job}' job, got {carrying}")
    for root in (LINT_WORKFLOWS_JOB, VALIDATE_RELEASE_PLAN_JOB, MIRROR_IMAGES_JOB):
        needs = job_needs(jobs_value[root]) if root in jobs_value else []
        if needs:
            problems.append(f"{path}: job '{root}' is a parallel root and must carry no needs, got {needs}")
    if PREFLIGHT_JOB in jobs_value:
        expected: set[str] = {LINT_WORKFLOWS_JOB}
        if MIRROR_IMAGES_JOB in jobs_value:
            expected.add(MIRROR_IMAGES_JOB)
        actual = set(job_needs(jobs_value[PREFLIGHT_JOB]))
        if actual != expected:
            problems.append(
                f"{path}: job '{PREFLIGHT_JOB}' must need {sorted(expected)} (contract breaks kill the battery early),"
                f" got {sorted(actual)}"
            )
    writer_jobs = [
        str(job_name)
        for job_name, job_value in jobs_value.items()
        if is_mapping(job_value) and job_has_cache_writing_setup_uv(job_value)
    ]
    expected_writer = PREFLIGHT_JOB if PREFLIGHT_JOB in jobs_value else LINT_WORKFLOWS_JOB
    if len(writer_jobs) != 1:
        problems.append(
            f"{path}: integrate.yml must carry exactly one cache-writing setup-uv step ({expected_writer}'s saver),"
            f" found {len(writer_jobs)}"
        )
    elif writer_jobs != [expected_writer]:
        problems.append(f"{path}: the cache-writing setup-uv must live in '{expected_writer}', found {writer_jobs}")
    return problems


def validate_release_contract(
    document: dict[object, object], verbs_by_job: dict[str, list[str]], path: Path
) -> list[str]:
    problems: list[str] = []
    if document.get("name") != RELEASE_WORKFLOW_NAME:
        problems.append(f"{path}: workflow name must be {RELEASE_WORKFLOW_NAME}")
    concurrency = document.get("concurrency")
    if not is_mapping(concurrency) or concurrency.get("group") != RELEASE_CONCURRENCY:
        problems.append(f"{path}: concurrency group must be {RELEASE_CONCURRENCY} (the per-ref delivery queue)")
    elif "cancel-in-progress" in concurrency:
        problems.append(f"{path}: concurrency must omit cancel-in-progress — the queue is the delivery mutex")
    carrying = [job_name for job_name, verbs in verbs_by_job.items() if RELEASE_JOB in verbs]
    if carrying and carrying != [RELEASE_JOB]:
        problems.append(f"{path}: the release verb must run in the '{RELEASE_JOB}' job, got {carrying}")
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


def validate_job(job_name: str, job_value: object, path: Path, nuget: bool = False) -> tuple[list[str], list[VerbStep]]:
    if not is_mapping(job_value):
        return [f"{path}: job '{job_name}' is not a mapping"], []
    problems: list[str] = []
    if "environment" in job_value:
        problems.append(f"{path}: job '{job_name}': environment: key is forbidden (the fleet runs environment-less)")
    steps_value = job_value.get("steps")
    steps = steps_value if is_object_list(steps_value) else []
    checkout_steps, checkout_problems = collect_checkout_steps(job_name, steps, path)
    problems.extend(checkout_problems)
    verb_steps, verb_problems = collect_verb_steps(job_name, steps, path, nuget)
    problems.extend(verb_problems)
    problems.extend(collect_dead_uses(job_name, steps, path))
    if not verb_steps:
        return problems, verb_steps
    is_merge_gate_job = any(verb.name == "merge-gate" for verb in verb_steps)
    is_release_job = any(verb.name == "release" for verb in verb_steps)
    is_delivery_job = any(verb.name in NUGET_DELIVERY_VERBS for verb in verb_steps)
    if not is_release_job and any(step.signature == CHECKOUT_WITH_TAGS_PUSH for step in checkout_steps):
        problems.append(f"{path}: job '{job_name}': checkout-with-tags-push is reserved for release jobs")
    if not is_merge_gate_job and any(step.signature == MERGE_BOT for step in checkout_steps):
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
        return problems, verb_steps
    earliest_wrapper_index = min(wrappers_before)
    required_checkouts = {VERB_CHECKOUTS[verb.name] for verb in verb_steps}
    for required in sorted(required_checkouts):
        if not any(step.signature == required and step.step_index < earliest_wrapper_index for step in checkout_steps):
            problems.append(f"{path}: job '{job_name}': no {required} checkout precedes the setup-release-devkit step")
    if not any(
        is_mapping(step_value) and is_canonical_setup_uv(step_value) and index < earliest_wrapper_index
        for index, step_value in enumerate(steps)
    ):
        problems.append(
            f"{path}: job '{job_name}': no canonical {SETUP_UV_USES} step"
            " (enable-cache: true with an explicit save-cache) precedes the setup-release-devkit step"
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
    nuget_login_indexes: list[int] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value) or step_value.get("uses") != NUGET_LOGIN_USES:
            continue
        if step_value.get("id") != "nuget-login" or step_value.get("with") != NUGET_LOGIN_INPUTS:
            problems.append(
                f"{path}: job '{job_name}' step {index}: NuGet/login must be the canonical mint step"
                " (id: nuget-login, user from the NUGET_USER org secret)"
            )
            continue
        nuget_login_indexes.append(index)
    if (
        is_delivery_job
        and nuget
        and not any(earliest_wrapper_index < index < first_verb_index for index in nuget_login_indexes)
    ):
        problems.append(
            f"{path}: job '{job_name}': nuget delivery jobs require a canonical {NUGET_LOGIN_USES} mint step"
            " between the wrapper and the verb"
        )
    if not is_delivery_job or not nuget:
        if any(is_mapping(step_value) and step_value.get("uses") == NUGET_LOGIN_USES for step_value in steps):
            problems.append(
                f"{path}: job '{job_name}': {NUGET_LOGIN_USES} is reserved for the delivery jobs"
                " of repos whose release-devkit.yaml declares a nuget registry"
            )
    return problems, verb_steps


def job_needs(job_value: object) -> list[str]:
    if not is_mapping(job_value):
        return []
    needs_value = job_value.get("needs")
    if isinstance(needs_value, str):
        return [needs_value]
    if is_object_list(needs_value):
        return [str(entry) for entry in needs_value]
    return []


def job_has_cache_writing_setup_uv(job_value: dict[object, object]) -> bool:
    steps_value = job_value.get("steps")
    steps = steps_value if is_object_list(steps_value) else []
    return any(is_mapping(step_value) and is_cache_writing_setup_uv(step_value) for step_value in steps)


def validate_run_steps_single_line(raw_lines: list[str], path: Path) -> list[str]:
    problems: list[str] = []
    for index, line in enumerate(raw_lines):
        match = RUN_STEP_LINE.match(line)
        if not match:
            continue
        value = (match.group("value") or "").strip()
        run_column = len(line) - len(line.lstrip()) + len(match.group("prefix").lstrip())
        if not value or value in BLOCK_SCALAR_HEADS:
            if value == ">-":
                block: list[str] = []
                for entry in raw_lines[index + 1 :]:
                    if entry.strip() and len(entry) - len(entry.lstrip()) <= run_column:
                        break
                    block.append(entry)
                stripped = [entry.strip() for entry in block if entry.strip()]
                if len(stripped) != len(block):
                    problems.append(
                        f"{path}: line {index + 1}: run: steps must be a single physical line"
                        " (folded blocks may not contain blank lines)"
                    )
                elif not stripped:
                    problems.append(
                        f"{path}: line {index + 1}: run: steps must be a single physical line (empty folded block)"
                    )
                elif len({len(entry) - len(entry.lstrip()) for entry in block}) != 1:
                    problems.append(
                        f"{path}: line {index + 1}: run: steps must be a single physical line"
                        " (folded continuations must share one indent)"
                    )
                else:
                    joined = " ".join(stripped)
                    if len(joined) <= RUN_STEP_FOLD_THRESHOLD:
                        problems.append(
                            f"{path}: line {index + 1}: run: steps must be a single physical line"
                            f" (folds are allowed only for commands longer than {RUN_STEP_FOLD_THRESHOLD} characters)"
                        )
                    elif "release-devkit" in joined:
                        problems.append(
                            f"{path}: line {index + 1}: run: steps must be a single physical line"
                            " (devkit verb invocations never fold)"
                        )
            else:
                problems.append(
                    f"{path}: line {index + 1}: run: steps must be a single physical line (no folded or literal blocks)"
                )
            continue
        follow_up = next((entry for entry in raw_lines[index + 1 :] if entry.strip()), "")
        if follow_up and len(follow_up) - len(follow_up.lstrip()) > run_column:
            problems.append(
                f"{path}: line {index + 1}: run: steps must be a single physical line (folded continuation follows)"
            )
    return problems


def is_canonical_setup_uv(step_value: dict[object, object]) -> bool:
    if step_value.get("uses") != SETUP_UV_USES:
        return False
    with_block = step_value.get("with")
    if not is_string_mapping(with_block):
        return False
    return any(with_block == inputs for inputs in (SETUP_UV_RESTORE_INPUTS, SETUP_UV_SAVE_INPUTS))


def is_cache_writing_setup_uv(step_value: dict[object, object]) -> bool:
    if step_value.get("uses") != SETUP_UV_USES:
        return False
    with_block = step_value.get("with")
    if not is_string_mapping(with_block):
        return False
    return with_block.get("enable-cache") is True and with_block.get("save-cache") != "false"


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


def collect_verb_steps(
    job_name: str, steps: list[object], path: Path, nuget: bool = False
) -> tuple[list[VerbStep], list[str]]:
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
            problems.extend(validate_verb_env(job_name, index, verb, step_value, path, nuget))
            verb_steps.append(VerbStep(step_index=index, name=verb))
    return verb_steps, problems


def validate_verb_env(
    job_name: str, step_index: int, verb: str, step_value: dict[object, object], path: Path, nuget: bool = False
) -> list[str]:
    problems: list[str] = []
    env_value = step_value.get("env")
    env: dict[object, object] = env_value if is_mapping(env_value) else {}
    for key, value in VERB_ENV.get(verb, {}).items():
        if env.get(key) != value:
            problems.append(f"{path}: job '{job_name}' step {step_index}: {verb} requires env {key}: {value}")
    if verb in NUGET_DELIVERY_VERBS:
        api_key_value = env.get(NUGET_API_KEY_ENV)
        if nuget and api_key_value != NUGET_API_KEY_SOURCE:
            problems.append(
                f"{path}: job '{job_name}' step {step_index}: {verb} requires env"
                f" {NUGET_API_KEY_ENV}: {NUGET_API_KEY_SOURCE}"
            )
        if not nuget and api_key_value is not None:
            problems.append(
                f"{path}: job '{job_name}' step {step_index}: {verb} must not carry {NUGET_API_KEY_ENV} env"
                " (the release-devkit.yaml declares no nuget registry)"
            )
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
        signature = next((name for name, expected in signatures_for(path).items() if with_block == expected), None)
        if signature is None:
            rendered = json.dumps(with_block, sort_keys=True)
            problems.append(f"{path}: job '{job_name}' step {index}: checkout matches no signature; with={rendered}")
        else:
            checkout_steps.append(CheckoutStep(step_index=index, signature=signature))
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
    cache_directory = Path.home() / ".cache" / "release-devkit" / f"actionlint-v{ACTIONLINT_VERSION}"
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


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")
